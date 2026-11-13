"""The basic dictionary packs (polyglotic-hq project 164), end to end on
small fixtures in the sources' real formats: Wiktionary as kaikki.org
extracts it, JMdict as jmdict-simplified's JSON, the JLPT CSV, wordfreq."""

import gzip
import json
import sys
import zipfile
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from tests.tools.wordfreq_data import msgpack
from tools.dictionaries import kaikki, packs

from polyglotic_desktop.adapters.sqlite_dictionary import SqliteDictionary
from polyglotic_desktop.core.lexicon.english import EnglishDictionary


def sense(gloss: str, form_of: str = "", **extra: object) -> dict[str, object]:
    out: dict[str, object] = {"glosses": [gloss], **extra}
    if form_of:
        out["form_of"] = [{"word": form_of}]
        out["tags"] = ["form-of"]
    return out


def line(word: str, pos: str, *senses: dict[str, object], **extra: object) -> str:
    obj = {"word": word, "pos": pos, "lang_code": "es", "senses": list(senses), **extra}
    return json.dumps(obj, ensure_ascii=False)


SPANISH = [
    line("casa", "noun", sense("house"), etymology_number=1),
    line("casa", "verb", sense("inflection of casar:", "casar"), etymology_number=2),
    line("casas", "noun", sense("plural of casa", "casa")),
    line("casas", "verb", sense("second-person singular of casar", "casar")),
    line("casar", "verb", sense("to marry")),
    line(
        "saber",
        "verb",
        sense("to know"),
        forms=[
            {"form": "es-conj", "tags": ["table-tags"]},
            {"form": "saber", "tags": ["infinitive"]},
            {"form": "sé", "tags": ["first-person", "present"]},
            {"form": "me sé", "tags": ["reflexive"]},
        ],
        sounds=[{"ipa": "/saˈbeɾ/"}],
    ),
    line("saber", "noun", sense("knowledge")),
    line("supe", "verb", sense("first-person singular preterite of saber", "saber")),
    line("decir", "verb", sense("to say")),
    line(
        "dímelo",
        "verb",
        sense(
            "imperative of decir",
            "decir combined with indirect object me and direct object lo",
        ),
    ),
    line("hacer", "verb", sense("to do"), sense("to make")),
    line("rarísimo", "adj", sense("very rare")),  # no frequency: cut
    line("a la vez", "phrase", sense("at once")),  # a phrase: not a word
    "not json {",
]


def ru(word: str, pos: str, *senses: dict[str, object], **extra: object) -> str:
    obj = {"word": word, "pos": pos, "lang_code": "ru", "senses": list(senses), **extra}
    return json.dumps(obj, ensure_ascii=False)


def forms(*pairs: tuple[str, str]) -> list[dict[str, object]]:
    """A headword's `forms`: (form, its tags space-separated)."""
    return [{"form": f, "tags": t.split()} for f, t in pairs]


RUSSIAN = [
    ru(
        "рука",
        "noun",
        sense("hand"),
        sense("arm"),
        forms=forms(
            ("рука́", "canonical feminine inanimate"),
            ("ruká", "romanization"),
            ("ручно́й", "adjective relational"),  # another word
            ("ру́чка", "diminutive"),  # another word
            ("ru-noun-table", "inflection-template"),
            ("ру́ку", "accusative singular"),
            ("ру́ки", "nominative plural"),
            ("руки́", "genitive singular"),
        ),
        sounds=[{"ipa": "[rʊˈka]"}],
    ),
    ru(
        "руку",
        "noun",
        sense("accusative singular of рука́ (ruká)", "рука́"),
        forms=forms(("ру́ку", "canonical")),
    ),
    ru(
        "говорить",
        "verb",
        sense("to speak, to talk"),
        forms=forms(
            ("говори́ть", "canonical imperfective"),
            ("сказа́ть", "perfective"),  # its aspect partner: another word
            ("говорю́", "first-person present singular"),
            ("говоря́щий", "active participle present"),
            ("говоря́", "adverbial participle present"),
            ("govorjú", "first-person present singular"),  # a romanisation
        ),
    ),
    ru(
        "сказать",
        "verb",
        sense("to say, to tell"),
        forms=forms(
            ("сказа́ть", "canonical perfective"),
            ("ска́занный", "participle passive past"),
            ("сказа́л", "masculine singular past"),
        ),
    ),
    ru("ещё", "adv", sense("still, yet")),  # ё: always stressed, no mark
    ru(
        "стоимость",
        "noun",
        {
            "glosses": ["cost, value, worth"],
            "form_of": [{"word": "стоить"}],
            "tags": ["form-of", "noun-from-verb"],
        },
        forms=forms(("сто́имость", "canonical")),
    ),
    ru(
        "США",
        "name",
        {
            "glosses": ["initialism of Соединённые Шта́ты Аме́рики: USA"],
            "alt_of": [{"word": "Соединённые Шта́ты Аме́рики"}],
            "tags": ["abbreviation", "alt-of", "initialism", "plural"],
        },
    ),
    ru(
        "я",
        "pron",
        sense("I"),
        # the table of every personal pronoun, on each one's page
        forms=forms(("её", "feminine genitive personal pronoun third-person")),
    ),
    ru("я", "character", sense("The thirty-third letter of the Russian alphabet")),
    ru("она", "pron", sense("she"), forms=forms(("она́", "canonical"))),
    ru("её", "pron", sense("genitive of она́", "она́")),
]
ZH = [
    json.dumps({"word": w, "pos": p, "lang_code": lc, "senses": s}, ensure_ascii=False)
    for w, p, lc, s in [
        ("рука", "noun", "ru", [{"glosses": ["手"]}]),
        ("casa", "noun", "es", [{"glosses": ["房子 [接 de]"]}]),
        ("decir", "verb", "es", [{"glosses": ["说"]}]),
        ("hacer", "unknown", "es", [{"glosses": ["做"]}]),  # no part of speech
        ("食べる", "verb", "ja", [{"glosses": ["吃"]}]),
        ("たべる", "soft-redirect", "ja", [{}]),
        ("する", "verb", "ja", [{"glosses": ["做"]}]),  # whose する?
    ]
]
JMDICT = {
    "version": "3.6.2",
    "dictDate": "2026-11-02",
    "words": [
        {
            "id": "1358280",
            "kanji": [{"common": True, "text": "食べる"}],
            "kana": [{"common": True, "text": "たべる"}],
            "sense": [{"misc": [], "gloss": [{"text": "to eat"}, {"text": "to have"}]}],
        },
        {
            "id": "1157170",
            "kanji": [{"common": False, "text": "為る"}],
            "kana": [{"common": True, "text": "する"}],
            "sense": [{"misc": ["uk"], "gloss": [{"text": "to do"}]}],
        },
        {
            "id": "1567440",  # usually written する too, but rare: cut
            "kanji": [{"common": False, "text": "掏る"}],
            "kana": [{"common": False, "text": "する"}],
            "sense": [{"misc": ["uk"], "gloss": [{"text": "to pickpocket"}]}],
        },
        {
            "id": "1581900",
            "kanji": [{"common": True, "text": "剃る"}],
            "kana": [
                {"common": True, "text": "そる"},
                {"common": False, "text": "する"},
            ],
            "sense": [{"misc": [], "gloss": [{"text": "to shave"}]}],
        },
        {
            "id": "9999999",
            "kanji": [],
            "kana": [{"common": False, "text": "ぬるぽ"}],
            "sense": [{"misc": [], "gloss": [{"text": "unranked"}]}],
        },
        {
            "id": "1508860",
            "kanji": [{"common": True, "text": "米軍"}],
            "kana": [{"common": True, "text": "べいぐん"}],
            "sense": [{"misc": [], "gloss": [{"text": "US armed forces"}]}],
        },
    ],
}
JLPT = "Kanji,Reading,Level\n食べる,たべる,5\nする,する,5\n"
FREQ = {
    "es": {200: ["casa", "saber", "decir"], 300: ["casar", "supe", "casas", "hacer"]},
    "ja": {200: ["する"], 300: ["食べる"], 400: ["剃る"]},
    "ru": {
        150: ["я", "её"],
        200: ["рука", "руку", "руки", "говорить", "еще", "сказано"],
        300: ["сказать", "стоимость", "сша", "говорю", "ещё", "она", "the"],
    },
}


def sources(folder: Path) -> dict[str, Path]:
    folder.mkdir()
    paths = {
        "kaikki-es": folder / "es.jsonl.gz",
        "kaikki-ru": folder / "ru.jsonl.gz",
        "kaikki-zh": folder / "zh.jsonl",
        "jmdict": folder / "jmdict.json.zip",
        "jlpt": folder / "jlpt.csv",
        "wordfreq": folder / "wordfreq.whl",
    }
    paths["kaikki-es"].write_bytes(gzip.compress("\n".join(SPANISH).encode("utf-8")))
    paths["kaikki-ru"].write_bytes(gzip.compress("\n".join(RUSSIAN).encode("utf-8")))
    paths["kaikki-zh"].write_text("\n".join(ZH), encoding="utf-8")
    with zipfile.ZipFile(paths["jmdict"], "w") as archive:
        archive.writestr(
            "jmdict-eng-3.6.2.json", json.dumps(JMDICT, ensure_ascii=False)
        )
    paths["jlpt"].write_text(JLPT, encoding="utf-8")
    with zipfile.ZipFile(paths["wordfreq"], "w") as wheel:
        for language, buckets in FREQ.items():
            data = msgpack(
                [
                    {"format": "cB", "version": 1},
                    *(buckets.get(i, []) for i in range(500)),
                ]
            )
            wheel.writestr(
                f"wordfreq/data/large_{language}.msgpack.gz", gzip.compress(data)
            )
    return paths


@pytest.fixture
def built(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    monkeypatch.setattr(packs, "REGISTRY", tmp_path / "registry")
    (tmp_path / "registry").mkdir()
    paths = sources(tmp_path / "upstream")
    out = tmp_path / "out"
    out.mkdir()
    for pack in packs.PACKS.values():
        packs.build(pack, paths, out)
    return out


def test_kaikki_lines_become_entries_and_form_relations() -> None:
    found = kaikki.read_language(kaikki.lines_of(SPANISH, "es"))
    assert [e.key for e in found.entries] == [
        "casa|noun|1",
        "casar|verb|",
        "saber|verb|",
        "saber|noun|",
        "decir|verb|",
        "hacer|verb|",
        "rarísimo|adj|",
    ]
    assert found.forms["casas"] == {"casa", "casar"}
    assert found.forms["dímelo"] == {"decir"}  # "combined with ..." dropped
    assert found.forms["sé"] == {"saber"}  # from saber's table
    assert "me sé" not in found.forms and "es-conj" not in found.forms
    assert found.entries[2].reading == "/saˈbeɾ/"


def test_the_spanish_pack_finds_lemmas_and_its_own_entries(built: Path) -> None:
    file = SqliteDictionary(built / "wiktes.sqlite")
    spanish = EnglishDictionary(file)  # the same lookup: lemma, then own
    assert file.info["tier"] == "basic" and file.info["language"] == "es"

    def first(word: str) -> str:
        return spanish.lookup(word)[0].meanings[0]

    assert first("casa") == "(noun) house"  # its own entry, not casar's
    assert first("casas") == "(noun) house"  # casa is commoner than casar
    assert first("supe") == "(verb) to know"  # the verb, as the source orders it
    assert first("dímelo") == "(verb) to say"
    assert first("sé") == "(verb) to know"
    assert spanish.lookup("rarísimo") == []  # no frequency rank: cut
    assert spanish.lookup("a la vez") == []
    assert all(e.entry_id.startswith("wiktes:") for e in spanish.lookup("hacer"))
    assert spanish.lookup("hacer")[0].meanings == ("(verb) to do", "(verb) to make")


def test_the_chinese_file_has_chinese_where_the_chinese_edition_has_it(
    built: Path,
) -> None:
    english = EnglishDictionary(SqliteDictionary(built / "wiktes.sqlite"))
    chinese = EnglishDictionary(SqliteDictionary(built / "wiktes-zh.sqlite"))
    assert chinese.lookup("casa")[0].meanings == ("房子",)  # its note trimmed
    # no part of speech in the Chinese edition: its meanings go on the
    # word's first entry
    assert chinese.lookup("hacer")[0].meanings == ("做",)
    assert chinese.lookup("supe")[0].meanings == ("(verb) to know",)  # English
    assert [e.entry_id for e in chinese.lookup("casa")] == [
        e.entry_id for e in english.lookup("casa")
    ]


def test_the_japanese_pack_has_readings_levels_and_kana_forms(built: Path) -> None:
    file = SqliteDictionary(built / "jmdict.sqlite")
    eat = file.records("食べる")
    assert [(r.headword, r.reading, r.meanings) for r in eat] == [
        ("食べる", "たべる", ("to eat; to have",))
    ]
    assert eat[0].levels == (("jlpt", 1),)  # N5
    assert file.records("たべる") == eat
    do = file.records("する")
    assert [r.headword for r in do] == ["する", "剃る"]  # usually kana, commonest
    assert do[0].levels == (("jlpt", 1),) and do[1].levels == ()
    assert file.records("ぬるぽ") == []  # no rank, no level: cut
    # wordfreq can't rank 米軍 (its tokenizer splits it), but JMdict marks
    # it common
    assert [r.meanings for r in file.records("米軍")] == [("US armed forces",)]
    zh = SqliteDictionary(built / "jmdict-zh.sqlite")
    assert zh.records("食べる")[0].meanings == ("吃",)
    # the Chinese edition's する is 為る's - the only common entry usually
    # written so - not 掏る's (rare) or 剃る's, whose kana it is too
    assert [r.meanings for r in zh.records("する")] == [("做",), ("to shave",)]


def test_the_russian_pack_finds_forms_without_stress_marks(built: Path) -> None:
    file = SqliteDictionary(built / "wiktru.sqlite")
    russian = EnglishDictionary(file)  # the same lookup: lemma, then own
    assert file.info["tier"] == "basic" and file.info["language"] == "ru"

    def first(word: str) -> tuple[str, str, str]:
        entry = russian.lookup(word)[0]
        return entry.headword, entry.reading, entry.meanings[0]

    # the reading is the headword with its stress marked
    assert first("рука") == ("рука", "рука́", "(noun) hand")
    # inflections, from the table and from a "form of" page, unmarked
    assert first("руку") == first("руки") == first("рука")
    assert first("говорю")[0] == "говорить"
    # ё spelled е, as most text writes it; nothing to mark on ё
    assert first("еще") == first("ещё") == ("ещё", "", "(adv) still, yet")
    # a participle declined as an adjective counts for its verb
    assert first("говорящая")[0] == "говорить"
    assert first("сказано")[0] == "сказать"
    # derived words and aspect partners are words of their own, not forms
    assert file.lemma("ручной") is None and file.lemma("ручка") is None
    assert file.lemma("сказать") is None
    assert file.lemma("govorju") is None
    assert first("стоимость") == ("стоимость", "сто́имость", "(noun) cost, value, worth")
    assert first("США")[2].startswith("(name) initialism of")
    # я's table of every pronoun doesn't make её я's; её's own page does
    assert [e.headword for e in russian.lookup("её")] == ["она"]
    # a letter of the alphabet is no entry: я is "I"
    assert [e.meanings for e in russian.lookup("я")] == [("(pron) I",)]
    assert all(e.entry_id.startswith("wiktru:") for e in russian.lookup("рука"))
    assert float(file.info["running_words"]) > 0.9  # "the": another script
    # each inflected form keeps its own stress: it moves, and two forms
    # can be written alike
    assert file.form_reading("руку") == "ру́ку"
    assert file.form_reading("руки") == "ру́ки, руки́"
    assert file.form_reading("говорю") == "говорю́"
    assert file.form_reading("рука") == ""  # its entry says it
    assert file.form_reading("ручки") == ""  # wordfreq never met it
    zh = EnglishDictionary(SqliteDictionary(built / "wiktru-zh.sqlite"))
    assert zh.lookup("руку")[0].meanings == ("手",)


def test_credits_name_each_pack_source_and_its_licence(built: Path) -> None:
    text = (built / "jmdict.CREDITS.md").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in text and "EDRDG" in text and "Jonathan Waller" in text
    spanish = (built / "wiktes.CREDITS.md").read_text(encoding="utf-8")
    assert "Wiktionary" in spanish and "wordfreq" in spanish


def test_a_pack_builds_byte_for_byte_the_same(
    built: Path, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    again = tmp_path / "again"
    again.mkdir()
    paths = {p.stem.split(".")[0]: p for p in (tmp_path / "upstream").iterdir()}
    named = {
        "kaikki-es": paths["es"],
        "kaikki-zh": paths["zh"],
        "jmdict": paths["jmdict"],
        "jlpt": paths["jlpt"],
        "wordfreq": paths["wordfreq"],
    }
    packs.build(packs.PACKS["es"], named, again)
    assert (again / "wiktes.sqlite").read_bytes() == (
        built / "wiktes.sqlite"
    ).read_bytes()


def test_an_entry_keeps_its_id_whatever_else_its_pack_keeps(
    built: Path, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A language's full dictionary in place of its basic pack - more
    entries, from the same source - gives every entry the basic pack had
    the ID it had, so the learner's words carry over unchanged (decision
    0089, polyglotic-hq 298)."""
    bigger = dict(FREQ)
    bigger["es"] = {**FREQ["es"], 400: ["rarísimo"]}  # one more word kept
    monkeypatch.setattr(sys.modules[__name__], "FREQ", bigger)
    paths = sources(tmp_path / "bigger-sources")
    out = tmp_path / "bigger"
    out.mkdir()
    packs.build(packs.PACKS["es"], paths, out)
    basic = SqliteDictionary(built / "wiktes.sqlite")
    full = SqliteDictionary(out / "wiktes.sqlite")
    ids = {r.entry_id for w in basic.headwords() for r in basic.records(w)}
    assert full.records("rarísimo") and not basic.records("rarísimo")
    for word in basic.headwords():
        assert [r.entry_id for r in basic.records(word)] == [
            r.entry_id for r in full.records(word) if r.entry_id in ids
        ]


def test_pack_names_fit_the_servers_entry_id_pattern() -> None:
    for pack in packs.PACKS.values():
        assert pack.name.isascii() and pack.name.isalnum() and pack.name.islower()
