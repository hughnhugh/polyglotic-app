"""The basic dictionaries behind the developer switch (decision 0035):
`main` opens the packs it finds, and the learning tools look a row's
words up in its language's pack - the learner's dictionary otherwise."""

import threading
from collections.abc import Sequence
from pathlib import Path

from pytest import MonkeyPatch
from tests.lexicon.test_basic import SPANISH, FakeSplit
from tests.tools.test_packs import sources
from tests.ui.fakes import chinese_tools
from tools.dictionaries import packs

from polyglotic_desktop import main
from polyglotic_desktop.core.lexicon.basic import BasicDictionary
from polyglotic_desktop.ports.word_split import SplitWord
from polyglotic_desktop.ui.learning import LearningTools


def test_main_opens_each_basic_pack_by_its_language(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(packs, "REGISTRY", tmp_path / "registry")
    (tmp_path / "registry").mkdir()
    paths = sources(tmp_path / "upstream")
    out = tmp_path / "packs"
    out.mkdir()
    for pack in packs.PACKS.values():
        packs.build(pack, paths, out)
    english = main.basic_dictionaries(out, "en")
    assert sorted(english) == ["es", "ja", "ru"]
    # "casa" is also casar's "he marries" since the Spanish forms (#255)
    assert [e.meanings[0] for e in english["es"].lookup("casa")] == [
        "(noun) house",
        "(verb) to marry",
    ]
    assert [e.headword for e in english["ja"].lookup("食べ")] == ["食べる"]
    # Russian's word split is simplemma's, as Spanish's (polyglotic-hq 298)
    assert [e.headword for e in english["ru"].lookup("Руку")] == ["рука"]
    chinese = main.basic_dictionaries(out, "zh")
    assert next(e.meanings[0] for e in chinese["es"].lookup("casa")) == "房子"
    assert main.basic_dictionaries(tmp_path / "none", "en") == {}
    # a cut-off pack is left out, not a reason the app can't start
    whole = (out / "wiktes.sqlite").read_bytes()
    (out / "wiktes.sqlite").write_bytes(whole[:4096])
    assert sorted(main.basic_dictionaries(out, "en")) == ["ja", "ru"]


def test_the_switch_is_off_by_default_and_takes_a_meanings_language() -> None:
    assert main.arguments([]).basic_dictionaries is None
    assert main.arguments(["--basic-dictionaries"]).basic_dictionaries == "en"
    assert main.arguments(["--basic-dictionaries", "zh"]).basic_dictionaries == "zh"


def test_a_rows_language_picks_its_basic_dictionary() -> None:
    chinese = chinese_tools()
    tools = LearningTools(
        chinese.vocabulary,
        chinese.dictionary,
        basic={"es": BasicDictionary(SPANISH, FakeSplit(), "es")},
    )
    assert (
        tools.is_basic("es") and not tools.is_basic("zh") and not tools.is_basic(None)
    )
    assert [e.headword for e in tools.lookup("supe", "es")] == ["saber"]
    assert tools.lookup("supe") == []  # the Chinese learner's dictionary
    assert tools.word_at("no lo supe", 7, "es") == (6, 10)
    assert tools.lookup("电脑", "zh") == tools.lookup("电脑")  # no pack: as before


class SlowSplit:
    """A word split whose first use loads its data, noting the thread."""

    def __init__(self) -> None:
        self.loaded_on: str | None = None
        self.loaded = threading.Event()

    def words(self, text: str) -> Sequence[SplitWord]:
        if self.loaded_on is None:
            self.loaded_on = threading.current_thread().name
            self.loaded.set()
        return FakeSplit().words(text)


def test_a_basic_dictionarys_word_split_loads_off_the_interface_thread() -> None:
    chinese = chinese_tools()
    split = SlowSplit()
    tools = LearningTools(
        chinese.vocabulary,
        chinese.dictionary,
        basic={"es": BasicDictionary(SPANISH, split, "es")},
    )
    tools.prepare()
    assert split.loaded.wait(5)
    assert split.loaded_on == "basic dictionaries"


def test_an_installed_copys_packs_are_kept_with_its_data_not_the_app(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An update replaces the install folder whole, and the Store's can't
    be written: packs there would be gone after the next update (decision
    0089, polyglotic-hq 298)."""
    install = tmp_path / "Local" / "Polyglotic" / "current"
    data = tmp_path / "Roaming" / "Polyglotic"
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "executable", str(install / "Polyglotic.exe"))
    folder = main.packs_folder(main.dictionaries_folder(), data)
    assert folder == data / "dictionaries"
    assert not folder.is_relative_to(install)
    monkeypatch.setattr(main.sys, "frozen", False)
    # from source: where tools.dictionaries.packs writes them
    built = Path("build/dictionaries")
    assert main.packs_folder(built, data) == built / "packs"
