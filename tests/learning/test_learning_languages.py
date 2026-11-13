"""The languages a learner learns (`core.learning.languages`; polyglotic-hq
262, 248's section 3, DECISIONS.md #65): every caption language in a tier,
one full dictionary in use at a time, the others in the order added, and
a lookup's "Learn Japanese too?" asked once."""

from polyglotic_desktop.core.learning.languages import (
    LearningLanguages,
    Tier,
    learned_code,
    starting_language,
    tier_of,
)


def test_each_language_is_in_one_tier() -> None:
    assert [tier_of(c) for c in ("zh", "en")] == [Tier.FULL, Tier.FULL]
    assert tier_of("ja") is tier_of("es") is Tier.BASIC
    assert tier_of("th") is tier_of("yue") is Tier.NONE


def test_chinese_in_either_script_is_one_language_and_cantonese_its_own() -> None:
    assert learned_code("zh-hant") == learned_code("zh") == "zh"
    assert learned_code("yue") == "yue"


def test_a_stored_list_is_made_consistent() -> None:
    found = LearningLanguages.of("zh", ("ja", "zh", "ja", "th"), ("th", "ko"))
    assert found.all == ("zh", "ja", "th")
    assert found.not_now == ("ko",)  # nothing both learned and "not now"


def test_the_first_full_dictionary_becomes_the_main_language() -> None:
    nothing = LearningLanguages()
    assert nothing.added("ja") == LearningLanguages(None, ("ja",))  # can't run
    assert nothing.added("ja").added("en").main == "en"
    assert LearningLanguages("zh").added("en") == LearningLanguages("zh", ("en",))


def test_switching_keeps_the_old_language_learned_and_first_after() -> None:
    languages = LearningLanguages("zh", ("ja", "en"))
    switched = languages.switched_to("en")
    assert switched == LearningLanguages("en", ("zh", "ja"))
    assert languages.switched_to("ja") == languages  # basic: lookups only
    assert switched.switched_to("zh") == LearningLanguages("zh", ("en", "ja"))


def test_the_main_language_cant_be_stopped_the_others_can() -> None:
    languages = LearningLanguages("zh", ("ja",))
    assert languages.stopped("zh") == languages
    assert languages.stopped("ja") == LearningLanguages("zh")


def test_a_lookup_asks_once_about_a_language_with_a_dictionary() -> None:
    languages = LearningLanguages("zh")
    assert languages.asks_about("ja") == "ja"
    assert languages.asks_about("en") == "en"
    assert languages.asks_about("zh-hant") is None  # learned already
    assert languages.asks_about("th") is None  # no dictionary to learn with
    assert languages.asks_about(None) is None
    assert languages.declined("ja").asks_about("ja") is None  # "Not now": once
    assert languages.added("ja").asks_about("ja") is None


def nothing_kept(code: str) -> bool:
    return False


def test_the_language_learned_runs_once_its_chosen() -> None:
    """polyglotic-hq 293: the first run asks no language; once Learning has
    one, it's the one whose learning data runs."""
    assert starting_language("en", "zh", nothing_kept) == "en"
    assert starting_language("zh", "zh", lambda c: c == "en") == "zh"


def test_until_one_is_chosen_english_unless_its_the_learners_own() -> None:
    """A guess from Windows' first display language: an English PC's
    learner is learning something else - Chinese, the other full
    dictionary - and anyone else most likely English."""
    assert starting_language(None, "en", nothing_kept) == "zh"
    assert starting_language(None, "zh", nothing_kept) == "en"
    assert starting_language(None, "ja", nothing_kept) == "en"
    assert starting_language(None, None, nothing_kept) == "en"


def test_learning_data_kept_for_the_other_keeps_it_running() -> None:
    """An install from before ran Chinese until a language was chosen: on a
    Japanese PC its words stay in view, rather than an empty English list."""
    assert starting_language(None, "ja", lambda c: c == "zh") == "zh"
    assert starting_language(None, "ja", lambda c: True) == "en"  # both: the guess
    assert starting_language(None, "en", lambda c: c == "en") == "en"
