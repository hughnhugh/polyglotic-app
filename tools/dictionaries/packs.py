"""The basic dictionary packs: one pipeline, a config per language.

    uv run python -m tools.dictionaries.packs            # every pack
    uv run python -m tools.dictionaries.packs es ja      # some

polyglotic-hq project 157 proposed "basic" dictionaries for the caption
languages beyond Chinese and English, from open data and one pipeline
(DECISIONS #65 asks the user whether they are a launch goal; until then
nothing here reaches learners: the installer ships `cedict` and `ecdict`
only, and `build` doesn't make these).

Each language's config names its sources and a reader that turns them
into a `Draft`: entries with English meanings (and Chinese ones where the
Chinese edition of Wiktionary has them), the written forms that find
them, and inflected forms -> their lemma. The rest is shared: entry IDs
(decision 0007, a registry per pack), frequency ranks from wordfreq, the
SQLite file in the lookup's own format (decision 0009), its credits, and
the coverage probe (`coverage`): its share goes in the file's `info`, and
the build fails if a pack is under the basic tier's floor.

Each pack is written twice, once per meanings language: `<name>.sqlite`
(English) and `<name>-zh.sqlite` (Chinese where there is Chinese, else
English) - the same entries and IDs, so statuses don't care which.
Files go to `build/dictionaries/packs/` with `<name>.CREDITS.md`.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from polyglotic_desktop.adapters.sqlite_dictionary import (
    FORMAT,
    add_info,
    write_dictionary,
)
from polyglotic_desktop.ports.dictionary import EntryRecord
from tools.dictionaries import (
    coverage,
    jmdict,
    kaikki,
    russian,
    spanish,
    wordfreq_ranks,
)
from tools.dictionaries.entry_ids import Registry, assign_ids
from tools.dictionaries.sources import (
    JLPT,
    JMDICT,
    KAIKKI_ES,
    KAIKKI_RU,
    KAIKKI_ZH,
    MIT,
    WORDFREQ,
    Source,
    fetch,
)

REPO = Path(__file__).resolve().parents[2]
REGISTRY = Path(__file__).parent / "registry"
CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/"


@dataclass
class DraftEntry:
    """One entry before it has an ID or a rank. `ranked_by`: the written
    forms whose frequencies are its own (inflections are added through
    the draft's `inflections`)."""

    key: str
    headword: str
    reading: str
    meanings: tuple[str, ...]
    ranked_by: tuple[str, ...]
    zh_meanings: tuple[str, ...] = ()
    levels: tuple[tuple[str, int], ...] = ()
    common: bool = False
    """The source marks it common (JMdict's priority lists): kept
    whatever wordfreq says."""


@dataclass
class Draft:
    entries: list[DraftEntry]
    forms: dict[str, list[str]]
    """Written form -> entry keys, best first (the form's own entries)."""
    inflections: dict[str, set[str]] = field(default_factory=dict)
    """Inflected form -> the headwords it is a form of (all of them)."""
    imperative: set[tuple[str, str]] = field(default_factory=set)
    """(form, lemma) pairs that are only an imperative (`kaikki.Language`)."""
    verb_forms: set[tuple[str, str]] = field(default_factory=set)
    """(form, lemma) pairs where the form is the verb's inflection."""
    form_readings: dict[str, list[str]] = field(default_factory=dict)
    """Written form -> how it is said, where the source marks a form apart
    from its headword (Russian's stress), each way once, in order."""


@dataclass(frozen=True)
class Pack:
    """One language's pack: `name` is the file's name and the entry IDs'
    prefix (lower-case letters and digits: the server's pattern)."""

    language: str
    name: str
    title: str
    sources: tuple[Source, ...]
    read: Callable[[Mapping[str, Path]], Draft]
    level_schemes: str
    about: str  # what we changed, for the credits


# -- Spanish: Wiktionary --------------------------------------------------------


def chinese_for(
    word: str, pos: str, first: bool, zh: Mapping[str, list[str]]
) -> tuple[str, ...]:
    """The Chinese edition's meanings for one entry: those under the same
    part of speech; for a word's first entry, failing that, those under
    any (the Chinese edition often has none: casa is "unknown" there)."""
    if f"{word}|{pos}" in zh:
        return tuple(zh[f"{word}|{pos}"][: kaikki.MAX_MEANINGS])
    if not first:
        return ()
    found = [g for key, gs in zh.items() if key.split("|")[0] == word for g in gs]
    return tuple(dict.fromkeys(found))[: kaikki.MAX_MEANINGS]


def read_spanish(paths: Mapping[str, Path]) -> Draft:
    words = kaikki.read_language(kaikki.lines(paths["kaikki-es"], "es"))
    # pronominal verbs: levantarse, and the forms with te/se/nos it gets
    found = spanish.pronominal(words)
    words.entries += found.entries
    for entry in found.entries:
        words.forms.pop(entry.word, None)  # its own entry, not levantar's
    for form, verb in found.forms.items():
        words.forms[form] = {verb}
        words.verb_forms.add((form, verb))
    zh = kaikki.glosses_by_word(kaikki.lines(paths["kaikki-zh"], "es"))
    zh_by_word: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for key, glosses in zh.items():
        zh_by_word[key.split("|")[0]][key] = glosses
    entries = []
    forms: dict[str, list[str]] = defaultdict(list)
    for e in words.entries:
        entries.append(
            DraftEntry(
                key=e.key,
                headword=e.word,
                reading=e.reading,
                meanings=tuple(f"({e.pos}) {m}" if e.pos else m for m in e.meanings),
                ranked_by=(e.word,),
                zh_meanings=chinese_for(
                    e.word, e.pos, not forms[e.word], zh_by_word.get(e.word, {})
                ),
            )
        )
        forms[e.word].append(e.key)
    return Draft(
        entries,
        dict(forms),
        {f: set(ls) for f, ls in words.forms.items()},
        words.imperative,
        words.verb_forms,
    )


# -- Russian: Wiktionary ---------------------------------------------------------


def read_russian(paths: Mapping[str, Path]) -> Draft:
    """Wiktionary's Russian words with English meanings, readings with the
    stress marked, and inflections found without their stress marks
    (`russian`); Chinese meanings as Spanish's."""
    participles: list[tuple[str, str]] = []
    form_readings: dict[str, list[str]] = defaultdict(list)

    def objects() -> Iterator[dict[str, object]]:
        for obj in kaikki.lines(paths["kaikki-ru"], "ru"):
            for form, marked in russian.form_readings(obj):
                if marked not in form_readings[form]:
                    form_readings[form].append(marked)
            obj = russian.cleaned(obj)
            participles.extend(russian.participles(obj))
            yield obj

    words = kaikki.read_language(objects(), reading=russian.stressed)
    # a participle's declined forms count for its verb, unless the
    # participle is an adjective of its own (следующий: next) or the form
    # is already another word's
    headwords = {e.word for e in words.entries}
    for participle, verb in participles:
        if participle in headwords:
            continue
        for form in russian.declined(participle):
            if form not in words.forms and form not in headwords:
                words.forms[form].add(verb)
                words.verb_forms.add((form, verb))
    # a form of a form: "используется" is использоваться's, a passive
    # given only as "passive of использовать"; "лучшая" is лучший's, given
    # only as "superlative of хороший" - each counts for the word with an
    # entry
    for form, lemmas in words.forms.items():
        for lemma in [x for x in lemmas if x not in headwords]:
            for further in words.forms.get(lemma, set()) & headwords:
                lemmas.add(further)
                if (form, lemma) in words.verb_forms:
                    words.verb_forms.add((form, further))
    zh = kaikki.glosses_by_word(kaikki.lines(paths["kaikki-zh"], "ru"))
    zh_by_word: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for key, glosses in zh.items():  # the Chinese edition may mark stress
        plain = russian.unstressed(key)
        found = zh_by_word[plain.split("|")[0]].setdefault(plain, [])
        found += [g for g in glosses if g not in found]
    entries = []
    forms: dict[str, list[str]] = defaultdict(list)
    for e in words.entries:
        entries.append(
            DraftEntry(
                key=e.key,
                headword=e.word,
                reading=e.reading,
                meanings=tuple(f"({e.pos}) {m}" if e.pos else m for m in e.meanings),
                ranked_by=(e.word,),
                zh_meanings=chinese_for(
                    e.word, e.pos, not forms[e.word], zh_by_word.get(e.word, {})
                ),
            )
        )
        forms[e.word].append(e.key)
    return Draft(
        entries,
        dict(forms),
        {f: set(ls) for f, ls in words.forms.items()},
        words.imperative,
        words.verb_forms,
        dict(form_readings),
    )


# -- Japanese: JMdict -----------------------------------------------------------


def jlpt_levels(path: Path) -> dict[tuple[str, str], int]:
    """(written form, reading) -> level, 1 for N5 (the lowest) to 5 for N1.
    A word in kana alone has itself as its written form."""
    out: dict[tuple[str, str], int] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            n = int(row["Level"])
            key = (row["Kanji"].strip(), row["Reading"].strip())
            out[key] = min(out.get(key, 9), 6 - n)
    return out


def chinese_for_japanese(
    word: jmdict.JmdictWord,
    zh: Mapping[str, list[str]],
    kana_owner: Mapping[str, str],
) -> tuple[str, ...]:
    """The Chinese edition's meanings for a JMdict entry: those of its
    first kanji form the edition has (年's entries share 年's), else those
    of its kana if it owns the kana (`kana_owners`): かみ could be 神, 髪
    or 紙, but する is 為る, usually written する."""
    for kanji in word.kanji:
        if kanji in zh:
            return tuple(zh[kanji][: jmdict.MAX_MEANINGS])
    for kana in word.kana:
        if kana in zh and kana_owner.get(kana) == word.seq:
            return tuple(zh[kana][: jmdict.MAX_MEANINGS])
    return ()


def kana_owners(words: Sequence[jmdict.JmdictWord]) -> dict[str, str]:
    """Kana -> the entry its meanings belong to: the only entry written
    with it; or else the only common entry usually written in it (する:
    為る, not 掏る, "to pickpocket")."""
    written: dict[str, list[jmdict.JmdictWord]] = defaultdict(list)
    for w in words:
        for kana in w.kana:
            written[kana].append(w)
    owners = {}
    for kana, found in written.items():
        if len(found) == 1:
            owners[kana] = found[0].seq
            continue
        usual = [w for w in found if w.headword == kana and w.common]
        if len(usual) == 1:
            owners[kana] = usual[0].seq
    return owners


def usual_in_kana(word: jmdict.JmdictWord, kana_owner: Mapping[str, str]) -> bool:
    """Whether the kana it's usually written in is this entry's to count:
    it owns the kana (`kana_owners`), or no entry does and JMdict marks
    this one common (なる is both 成る, "to become", and 生る, "to bear
    fruit"). 掏る, "to pickpocket", is usually written する too, but rare."""
    owner = kana_owner.get(word.headword)
    return owner == word.seq or (owner is None and word.common)


def ranked_by(
    word: jmdict.JmdictWord, kana_owner: Mapping[str, str]
) -> tuple[str, ...]:
    """The forms whose frequency is a JMdict entry's: its headword - a
    kana headword only if it's this entry's to count (`usual_in_kana`);
    else its kanji's."""
    if word.headword not in word.kana or usual_in_kana(word, kana_owner):
        return (word.headword,)
    return word.kanji[:1]


def japanese(paths: Mapping[str, Path]) -> Draft:
    _, words = jmdict.read(paths["jmdict"])
    zh = kaikki.glosses_by_word(kaikki.lines(paths["kaikki-zh"], "ja"))
    zh_by_word: dict[str, list[str]] = defaultdict(list)
    for word_pos, glosses in zh.items():
        word = word_pos.split("|")[0]
        zh_by_word[word] += [g for g in glosses if g not in zh_by_word[word]]
    owners = kana_owners(words)
    levels = jlpt_levels(paths["jlpt"])
    entries = []
    forms: dict[str, list[str]] = defaultdict(list)
    for w in words:
        # a word listed in kana alone is the entry that owns the kana
        pairs = [(k, kana) for k in w.kanji for kana in w.kana]
        if w.headword in w.kana and usual_in_kana(w, owners):
            pairs.append((w.headword, w.headword))
        level = min((levels[p] for p in pairs if p in levels), default=None)
        entries.append(
            DraftEntry(
                key=w.seq,
                headword=w.headword,
                reading=w.reading,
                meanings=w.meanings,
                ranked_by=ranked_by(w, owners),
                zh_meanings=chinese_for_japanese(w, zh_by_word, owners),
                levels=(("jlpt", level),) if level else (),
                common=w.common,
            )
        )
        for written in w.written:
            forms[written].append(w.seq)
    return Draft(entries, dict(forms))


PACKS = {
    "es": Pack(
        language="es",
        name="wiktes",
        title="Spanish",
        sources=(KAIKKI_ES, KAIKKI_ZH, WORDFREQ),
        read=read_spanish,
        level_schemes="es-frequency",
        about=(
            "Wiktionary's Spanish words with their English meanings (and the "
            "Chinese edition's Chinese meanings in the -zh file), IPA and "
            "inflections, cut to the words wordfreq ranks, with frequency ranks "
            "from wordfreq"
        ),
    ),
    "ru": Pack(
        language="ru",
        name="wiktru",
        title="Russian",
        sources=(KAIKKI_RU, KAIKKI_ZH, WORDFREQ),
        read=read_russian,
        level_schemes="ru-frequency",
        about=(
            "Wiktionary's Russian words with their English meanings (and the "
            "Chinese edition's Chinese meanings in the -zh file), the stress "
            "marked as Wiktionary marks it, and inflections, found without "
            "their stress marks and with е for ё; cut to the words wordfreq "
            "ranks, with frequency ranks from wordfreq"
        ),
    ),
    "ja": Pack(
        language="ja",
        name="jmdict",
        title="Japanese",
        sources=(JMDICT, KAIKKI_ZH, JLPT, WORDFREQ),
        read=japanese,
        level_schemes="jlpt ja-frequency",
        about=(
            "JMdict's words with their kana readings and English meanings (and "
            "the Chinese edition of Wiktionary's Chinese meanings in the -zh "
            "file), unofficial JLPT levels, and frequency ranks from wordfreq"
        ),
    ),
}


# -- shared ---------------------------------------------------------------------


def frequency_of(word: str, freq: Mapping[str, float]) -> float:
    """`word`'s frequency in wordfreq's list, in lower case. A hyphenated
    word wordfreq hasn't got whole (its tokens split at hyphens:
    премьер-министр) gets what wordfreq gives a phrase of its parts - one
    over the sum of one over each part's - or 0 if a part is missing."""
    word = word.lower()
    if word in freq or "-" not in word:
        return freq.get(word, 0.0)
    parts = [freq.get(p, 0.0) for p in word.split("-") if p]
    if not parts or not all(parts):
        return 0.0
    return 1 / sum(1 / f for f in parts)


def frequencies(draft: Draft, freq: Mapping[str, float]) -> dict[str, float]:
    """Entry key -> its frequency: the forms it is written in plus those of
    its inflections that have no entry of their own (a form with one
    counts for that entry only: "casa", house, doesn't make casar, to
    marry, common)."""
    by_headword: dict[str, list[str]] = defaultdict(list)
    total: dict[str, float] = {}
    for e in draft.entries:
        by_headword[e.headword].append(e.key)
        total[e.key] = sum(frequency_of(w, freq) for w in set(e.ranked_by))
    for form, lemmas in draft.inflections.items():
        f = 0.0 if form in by_headword else frequency_of(form, freq)
        if f:
            for lemma in lemmas:
                for key in by_headword.get(lemma, ()):
                    total[key] += f
    return total


def ranks(draft: Draft, total: Mapping[str, float]) -> dict[str, int]:
    """Entry key -> frequency rank (1 = commonest), by `frequencies`.
    Entries of one word share its frequency and keep the source's order.
    Unranked entries are left out."""
    order = {e.key: n for n, e in enumerate(draft.entries)}  # ties: the source's
    ranked = sorted(
        (k for k in total if total[k] > 0), key=lambda k: (-total[k], order[k])
    )
    return {key: n for n, key in enumerate(ranked, start=1)}


IMPERATIVE_WEIGHT = 0.01
"""How much an imperative-only link counts when a form has several lemmas:
"sé" is saber's "I know" far more often than ser's "be!", though ser is
the commoner verb (polyglotic-hq 174's hard forms)."""


def lemma_table(
    draft: Draft,
    kept: set[str],
    total: Mapping[str, float],
    freq: Mapping[str, float],
) -> tuple[dict[str, str], dict[str, str]]:
    """Inflected form -> the lemma it counts for (decision 0035):
    - of its lemmas the pack keeps, the commonest - an imperative-only
      link weighed down (`IMPERATIVE_WEIGHT`);
    - a form with an entry of its own too ("era": an age, and ser's "was")
      gets its lemma first only if it is that verb's inflection and the
      verb's other forms are at least as common as the form itself - "era"
      counts for ser; "casa" stays a house, not casar's "marries"; a noun's
      or adjective's forms and other spellings keep their own entry first
      ("gafas", glasses; "neta", truth).
    The lookup shows the lemma's entries, then the form's own. Returns
    that table, and form -> the lemma to show *after* the form's own
    entries, for the forms that keep theirs first ("casa": house, then
    casar)."""
    family: dict[str, float] = {}
    for e in draft.entries:
        if e.key in kept:
            family[e.headword] = max(family.get(e.headword, 0.0), total[e.key])
    out, after = {}, {}
    for form, lemmas in draft.inflections.items():

        def weight(lemma: str, form: str = form) -> float:
            down = IMPERATIVE_WEIGHT if (form, lemma) in draft.imperative else 1.0
            return family[lemma] * down

        found = sorted((lemma for lemma in lemmas if lemma in family), key=str)
        if not found:
            continue
        best = max(found, key=weight)
        own = form in draft.forms and any(k in kept for k in draft.forms[form])
        if not own or (
            (form, best) in draft.verb_forms
            and weight(best) >= freq.get(form.lower(), 0.0)
        ):
            out[form] = best
        else:
            after[form] = best
    return out, after


@dataclass(frozen=True)
class Built:
    records: list[EntryRecord]
    forms: dict[str, list[str]]
    lemmas: dict[str, str]
    zh: dict[str, tuple[str, ...]]
    """Entry ID -> its Chinese meanings (none: it keeps its English)."""
    form_readings: dict[str, str]
    """Written form -> how it is said ("ру́ки, руки́"), for the forms a
    lookup shows as another word's (inflections, other spellings) that
    wordfreq has met."""
    stats: dict[str, object]


def assemble(pack: Pack, draft: Draft, registry: Registry, wordfreq: Path) -> Built:
    """IDs, ranks and the cut: entries with a frequency rank (the words a
    learner can meet), a level, or the source's own "common" mark."""
    freq = wordfreq_ranks.frequencies(wordfreq, pack.language)
    total = frequencies(draft, freq)
    rank_of = ranks(draft, total)
    kept_entries = [
        e for e in draft.entries if e.key in rank_of or e.levels or e.common
    ]
    kept = {e.key for e in kept_entries}
    ids = assign_ids(registry, kept)
    records = [
        EntryRecord(
            entry_id=ids[e.key],
            headword=e.headword,
            traditional="",
            reading=e.reading,
            meanings=e.meanings,
            frequency_rank=rank_of.get(e.key),
            levels=e.levels,
        )
        for e in kept_entries
    ]
    record_rank = {ids[k]: rank_of.get(k, 1 << 30) for k in kept}
    forms = {}
    for form, keys in draft.forms.items():
        found = [ids[k] for k in keys if k in kept]
        if found:
            # the commonest entry first; the source's order breaks ties
            forms[form] = sorted(found, key=lambda i: record_rank[i])
    lemmas, after = lemma_table(draft, kept, total, freq)
    for form, lemma in after.items():
        then = [i for i in forms.get(lemma, ()) if i not in forms[form]]
        forms[form] = forms[form] + then
    headwords = {r.headword for r in records}
    form_readings = {
        form: ", ".join(said)
        for form, said in sorted(draft.form_readings.items())
        if (form in lemmas or (form in forms and form not in headwords))
        and frequency_of(form, freq) > 0
    }
    with_zh = sum(1 for e in kept_entries if e.zh_meanings)
    stats: dict[str, object] = {
        "entries": len(records),
        "of source entries": len(draft.entries),
        "ranked": sum(1 for r in records if r.frequency_rank),
        "with a level": sum(1 for r in records if r.levels),
        "written forms": len(forms),
        "inflected forms": len(lemmas),
        "forms with their own reading": len(form_readings),
        "with Chinese meanings": f"{with_zh} ({100 * with_zh / max(1, len(records)):.1f} %)",
    }
    zh = {ids[e.key]: e.zh_meanings for e in kept_entries}
    return Built(records, forms, lemmas, zh, form_readings, stats)


def info(pack: Pack, meanings: str) -> dict[str, str]:
    return {
        "dictionary": pack.name,
        "language": pack.language,
        "tier": "basic",
        "meanings_language": meanings,
        "licence": "CC BY-SA 4.0",
        "sources": "; ".join(
            f"{s.name} {s.version} sha256:{s.sha256}" for s in pack.sources
        ),
        "frequency_source": "wordfreq",
        "level_schemes": pack.level_schemes,
        "credits": f"{pack.name}.CREDITS.md, next to this file",
    }


def write_pack(pack: Pack, built: Built, out: Path) -> dict[str, Path]:
    """`<name>.sqlite` (English meanings) and `<name>-zh.sqlite` (Chinese
    meanings; an entry the Chinese edition hasn't got keeps its English)."""
    paths = {}
    for meanings in ("en", "zh"):
        records = built.records
        if meanings == "zh":
            records = [
                replace(r, meanings=built.zh[r.entry_id] or r.meanings) for r in records
            ]
        path = out / (
            f"{pack.name}.sqlite" if meanings == "en" else f"{pack.name}-zh.sqlite"
        )
        write_dictionary(
            path,
            info(pack, meanings),
            records,
            built.forms,
            lemmas=built.lemmas,
            form_readings=built.form_readings,
        )
        paths[meanings] = path
    return paths


def credits(pack: Pack) -> str:
    lines = [
        f"# {pack.title} dictionary pack - credits",
        "",
        f"`{pack.name}.sqlite` and `{pack.name}-zh.sqlite` are plain SQLite files,",
        "separate from the app: you may open, copy and reuse them under",
        f"**CC BY-SA 4.0** ({CC_BY_SA}).",
        f"Made from: {pack.about}. Changes: converted to SQLite; entries given IDs;",
        'senses that only say "form of" turned into links to their lemma.',
        "",
    ]
    for source in pack.sources:
        lines += [
            f"## {source.title}",
            "",
            f"- Used for: {source.used_for}",
            f"- Version: {source.version}",
            f"- From: {source.url}",
            f"- SHA-256: `{source.sha256}`",
            f"- Home: {source.homepage}",
            f"- Licence: {source.licence}",
            "",
        ]
        if source.licence == "MIT":
            lines += [source.notice, "", MIT, ""]
        elif source.licence == "CC BY":
            lines += [f"{source.notice}.", ""]
        else:
            lines += [f"{source.notice}. Licensed under CC BY-SA 4.0: {CC_BY_SA}", ""]
    return "\n".join(lines)


def build(pack: Pack, paths: Mapping[str, Path], out: Path) -> dict[str, object]:
    registry_path = REGISTRY / f"{pack.name}.tsv"
    registry = Registry.load(registry_path, pack.name)
    before = (dict(registry.ids), dict(registry.merged))
    draft = pack.read(paths)
    built = assemble(pack, draft, registry, paths["wordfreq"])
    files = write_pack(pack, built, out)
    (out / f"{pack.name}.CREDITS.md").write_text(
        credits(pack), encoding="utf-8", newline="\n"
    )
    if (registry.ids, registry.merged) != before:
        registry.save(registry_path)
        print(f"  ! {registry_path.name} changed (a hash was salted): commit it")
    stats = dict(built.stats)
    probed = coverage.probe(files["en"], pack.language)
    added = {"coverage": f"{probed.share:.4f}"}
    if pack.language in coverage.SCRIPTS:
        running = coverage.probe_running_words(
            files["en"], pack.language, paths["wordfreq"]
        )
        added["running_words"] = f"{running.share:.4f}"
        stats["running words"] = str(running)
    for path in files.values():
        add_info(path, added)
    stats["coverage"] = str(probed)
    stats["passes the basic floor"] = probed.share >= coverage.FLOORS["basic"]
    for path in files.values():
        stats[f"{path.name}"] = f"{path.stat().st_size / 1e6:.1f} MB"
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("languages", nargs="*", default=list(PACKS))
    parser.add_argument(
        "--sources", type=Path, default=REPO / "build" / "dictionary-sources"
    )
    parser.add_argument(
        "--out", type=Path, default=REPO / "build" / "dictionaries" / "packs"
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for language in args.languages:
        pack = PACKS[language]
        paths = {s.name: fetch(s, args.sources) for s in pack.sources}
        started = time.perf_counter()
        stats = build(pack, paths, args.out)
        print(
            f"{pack.name} ({language}), format {FORMAT}: "
            f"{time.perf_counter() - started:.0f}s"
        )
        for key, value in stats.items():
            print(f"  {key}: {value}")
        failed += not stats["passes the basic floor"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
