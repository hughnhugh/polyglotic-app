"""Chinese lookups (core.lexicon.chinese), with the proof of concept's
tests brought across (vc-translator `test_dictionary.py`): tone marks,
the word split (chengyu kept whole), the word under a character, parts,
English to Chinese, and everyday readings first - on a small sample of
real CC-CEDICT lines, through a fake dictionary file."""

import threading
from collections.abc import Iterable, Mapping

from pytest import MonkeyPatch
from tests.lexicon.sample import chinese_sample
from tools.dictionaries.entry_ids import default_id

from polyglotic_desktop.core.lexicon import chinese
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary, has_han
from polyglotic_desktop.core.lexicon.pinyin import mark_pinyin
from polyglotic_desktop.core.shared import EntryId


def dictionary() -> ChineseDictionary:
    ranks = {"人": 10, "游戏": 500, "打游戏": 40000}
    return ChineseDictionary(chinese_sample(frequency_ranks=ranks))


def words(text: str) -> list[str]:
    return [text[a:b] for a, b in dictionary().split(text)]


def test_numbered_pinyin_gets_tone_marks() -> None:
    assert mark_pinyin("dian4 nao3") == "diàn nǎo"
    assert mark_pinyin("nu:3 lu:4") == "nǚ lǜ"
    assert mark_pinyin("xiong2 gui4 liu2 hou4") == "xióng guì liú hòu"  # the last vowel
    assert mark_pinyin("Bei3 jing1 r5 m2") == "Běi jīng r m"


def test_lookups_in_either_script_with_idioms_and_names_flagged() -> None:
    d = dictionary()
    assert [e.reading for e in d.lookup("电脑")] == ["diàn nǎo"]
    assert d.lookup("電腦") == d.lookup("电脑")
    assert d.lookup("画蛇添足")[0].idiom and not d.lookup("电脑")[0].idiom
    assert d.lookup("北京")[0].is_name and not d.lookup("电脑")[0].is_name
    assert d.lookup("电脑")[0].entry_id == default_id(
        "cedict", "電腦 电脑 [dian4 nao3]"
    )


def test_lines_split_into_the_fewest_most_even_words() -> None:
    assert words("他画蛇添足了") == ["他", "画蛇添足", "了"]
    assert words("研究生命起源") == ["研究", "生命", "起源"]
    assert words("这个人") == ["这个", "人"]
    assert words("我们一起打游戏OK吧！") == [
        "我",
        "们",
        "一",
        "起",
        "打游戏",
        "OK",
        "吧",
        "！",
    ]
    assert words("用電腦") == ["用", "電腦"]


def test_ties_between_equally_short_even_splits_go_to_the_commoner_words() -> None:
    # 是非常简单: 是非|常 and 是|非常 are both two words of 2 and 1 characters;
    # 非常 is far commoner than 是非. Likewise 中|看到, 对|地球, 不|公平 (project 039).
    lines = """\
是 是 [shi4] /is; are; am; yes; to be/
非 非 [fei1] /to not be; not; wrong/
常 常 [chang2] /always; ever; often/
是非 是非 [shi4 fei1] /right and wrong; quarrel/
非常 非常 [fei1 chang2] /very; very much; unusual/
簡單 简单 [jian3 dan1] /simple/
的 的 [de5] /of; ~'s (possessive particle)/
不 不 [bu4] /(negative prefix); not; no/
公 公 [gong1] /public; collectively owned/
平 平 [ping2] /flat; level; equal/
不公 不公 [bu4 gong1] /unjust; unfair/
公平 公平 [gong1 ping2] /fair; impartial/
"""
    ranks = {
        "是": 3,
        "非常": 120,
        "是非": 9000,
        "常": 400,
        "不": 5,
        "公平": 900,
        "不公": 20000,
    }
    with_ranks = ChineseDictionary(chinese_sample(lines, frequency_ranks=ranks))
    assert ["是非常简单的"[a:b] for a, b in with_ranks.split("是非常简单的")] == [
        "是",
        "非常",
        "简单",
        "的",
    ]
    assert ["不公平"[a:b] for a, b in with_ranks.split("不公平")] == ["不", "公平"]
    # a word the frequency source doesn't rank counts as rare, and without
    # ranks the longer earlier word still wins the tie
    without = ChineseDictionary(chinese_sample(lines))
    assert ["不公平"[a:b] for a, b in without.split("不公平")] == ["不公", "平"]
    # ranks on only some of the words still decide a tie (人 is ranked, 个人 isn't)
    assert words("这个人") == ["这个", "人"]


def test_the_word_under_a_character_the_parts_of_a_word_and_pinyin_for_a_phrase() -> (
    None
):
    d = dictionary()
    assert d.word_at("他画蛇添足了", 3) == (1, 5)
    assert d.word_at("OK电脑", 0) is None and d.word_at("电脑", 5) is None
    assert d.parts("打游戏") == ["游戏"]
    assert d.pinyin_of("电脑游戏") == "diàn nǎo yóu xì"
    assert has_han("OK电脑") and not has_han("OK")


def test_english_to_chinese() -> None:
    d = dictionary()
    assert [e.headword for e in d.reverse_lookup("games")][:1] == ["游戏"]
    assert d.reverse_lookup("play games")[0].headword == "打游戏"  # "to play a game"
    assert d.reverse_lookup("computers")[0].headword == "电脑"
    assert [e.headword for e in d.reverse_lookup("Beijing")] == ["北京"]
    assert [e.headword for e in d.reverse_lookup("a person")][:1] == ["人"]
    assert d.reverse_lookup("xyzzy") == []


def test_everyday_readings_first() -> None:
    d = dictionary()
    assert [e.reading for e in d.lookup("足")] == ["zú", "jù"]  # zú is in more words
    assert d.lookup("还")[0].reading == "hái"  # though huán is in more
    assert [e.reading for e in d.lookup("了")] == ["le", "liǎo"]  # "variant of" last


def test_an_entry_by_its_id() -> None:
    d = dictionary()
    computer = d.lookup("电脑")[0]
    assert d.entry(computer.entry_id) == computer
    assert d.entry(EntryId("cedict:0000000000")) is None


def test_reverse_lookup_ranks_only_the_commonest_candidates(
    monkeypatch: MonkeyPatch,
) -> None:
    # "to" is in about 35,000 CC-CEDICT meanings; ranking them all took 2s.
    d = ChineseDictionary(chinese_sample(frequency_ranks={"这个": 20, "这": 30}))
    assert [e.headword for e in d.reverse_lookup("this")] == ["这个", "这", "个"]
    monkeypatch.setattr(chinese, "REVERSE_CANDIDATES", 1)
    assert [e.headword for e in d.reverse_lookup("this")] == ["这个"]


def test_opening_reads_nothing_and_prepare_reads_the_split_once(
    monkeypatch: MonkeyPatch,
) -> None:
    """polyglotic-hq project 110: the word split's ~0.2 s of reading waits
    for `prepare` (main runs it off the interface thread once the window
    shows) - or for the first split, which then reads it there."""
    file = chinese_sample()
    reads: list[str] = []
    headwords, ranks = file.headwords, file.frequency_ranks

    def counted_headwords() -> Iterable[str]:
        reads.append("words")
        return headwords()

    def counted_ranks() -> Mapping[str, int]:
        reads.append("ranks")
        return ranks()

    monkeypatch.setattr(file, "headwords", counted_headwords)
    monkeypatch.setattr(file, "frequency_ranks", counted_ranks)
    found = ChineseDictionary(file)
    assert reads == []
    found.prepare()
    found.prepare()
    assert reads == ["ranks", "words"]
    unprepared = ChineseDictionary(file)
    assert unprepared.is_word("北京")
    assert reads == ["ranks", "words", "ranks", "words"]


def test_the_split_data_is_read_once_however_many_threads_ask() -> None:
    """`prepare` runs off the interface thread at start (polyglotic-hq 136):
    a caller on another thread meanwhile waits for it rather than reading
    the headwords again, and `ready` says when the split can answer."""
    file = chinese_sample()
    reads: list[str] = []
    original = file.headwords

    def counted() -> Iterable[str]:
        reads.append("headwords")
        return original()

    file.headwords = counted  # type: ignore[method-assign]
    d = ChineseDictionary(file)
    assert not d.ready
    threads = [threading.Thread(target=d.prepare) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert d.ready
    assert reads == ["headwords"]
    assert words("打游戏") == ["打游戏"]  # and the split works as before
