"""Languages by name, for the new interface: the caption window's language
chip, the language spoken above a caption, and the Languages panel's
choices and notes.

The same names, codes and order as today's `ui.languages` (which this
package can't import - decision 0031; that module goes when `ui/` does).
The codes are protocol.md's; the names go through Qt's translation tools,
in the same "Languages" context, so one translation serves both.
"""

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QLocale

from polyglotic_desktop.core.listening.captions import Language

_CONTEXT = "Languages"

# code -> English name; translated where shown
_NAMES = {
    "en": QT_TRANSLATE_NOOP("Languages", "English"),
    "zh": QT_TRANSLATE_NOOP("Languages", "Chinese (Simplified)"),
    "zh-hant": QT_TRANSLATE_NOOP("Languages", "Chinese (Traditional)"),
    "yue": QT_TRANSLATE_NOOP("Languages", "Cantonese"),
    "fr": QT_TRANSLATE_NOOP("Languages", "French"),
    "pt": QT_TRANSLATE_NOOP("Languages", "Portuguese"),
    "es": QT_TRANSLATE_NOOP("Languages", "Spanish"),
    "ja": QT_TRANSLATE_NOOP("Languages", "Japanese"),
    "tr": QT_TRANSLATE_NOOP("Languages", "Turkish"),
    "ru": QT_TRANSLATE_NOOP("Languages", "Russian"),
    "ar": QT_TRANSLATE_NOOP("Languages", "Arabic"),
    "ko": QT_TRANSLATE_NOOP("Languages", "Korean"),
    "th": QT_TRANSLATE_NOOP("Languages", "Thai"),
    "it": QT_TRANSLATE_NOOP("Languages", "Italian"),
    "de": QT_TRANSLATE_NOOP("Languages", "German"),
    "vi": QT_TRANSLATE_NOOP("Languages", "Vietnamese"),
    "ms": QT_TRANSLATE_NOOP("Languages", "Malay"),
    "id": QT_TRANSLATE_NOOP("Languages", "Indonesian"),
    "tl": QT_TRANSLATE_NOOP("Languages", "Filipino"),
    "hi": QT_TRANSLATE_NOOP("Languages", "Hindi"),
    "pl": QT_TRANSLATE_NOOP("Languages", "Polish"),
    "cs": QT_TRANSLATE_NOOP("Languages", "Czech"),
    "nl": QT_TRANSLATE_NOOP("Languages", "Dutch"),
    "uk": QT_TRANSLATE_NOOP("Languages", "Ukrainian"),
}
# How a spoken language is named: Chinese speech is "Mandarin" - its
# target's name describes a script.
_SPOKEN = {"zh": QT_TRANSLATE_NOOP("Languages", "Mandarin"), "yue": "Cantonese"}
# DECISIONS.md #40, as today's `ui.languages` says it. No line says which
# spoken languages are captioned less accurately (#23's note): the user
# asked it gone, 2026-11-13
_NOT_OFFERED_NOTE = QT_TRANSLATE_NOOP(
    "Languages",
    "Mongolian and Kazakh aren't offered yet: the translation model writes "
    "them in a script most of their speakers don't read.",
)
# Offered once and taken off (#40): a saved choice of one falls back, and
# Home says so once (polyglotic-hq projects 088 and 144)
_TAKEN_OFF = {
    "mn": QT_TRANSLATE_NOOP("Languages", "Mongolian"),
    "kk": QT_TRANSLATE_NOOP("Languages", "Kazakh"),
}
_TAKEN_OFF_NOTE = QT_TRANSLATE_NOOP(
    "Languages",
    "Taken off your caption windows' languages, as they aren't offered any "
    "more: {languages}.",
)


def _tr(text: object) -> str:
    return QCoreApplication.translate(_CONTEXT, str(text))


def name_list(names: Iterable[str]) -> str:
    """Names in a list as the interface's language writes one: "Mongolian
    and Kazakh", "蒙古语和哈萨克语" (decision 0034)."""
    return QLocale().createSeparatedList(list(names))


def language_name(code: str) -> str:
    """A target language's name ("Chinese (Simplified)")."""
    name = _NAMES.get(code)
    return _tr(name) if name else code


def spoken_names(codes: Iterable[str]) -> str:
    """ "Mandarin", or "Mandarin + English" for a caption mixing languages."""
    return " + ".join(_spoken_name(code) for code in codes)


def _spoken_name(code: str) -> str:
    name = _SPOKEN.get(code) or _NAMES.get(code)
    return _tr(name) if name else code.upper()


def own_languages() -> list[str]:
    """The caption languages the learner reads: Windows' display languages
    that captions are translated into (`own_targets`), in their order."""
    return own_targets(QLocale.system().uiLanguages())


def target_languages(own: Sequence[str] | None = None) -> list[Language]:
    """Every language that can be picked: the learner's own first - `own`,
    else Windows' (`own_languages`) - then the rest by name. None is pinned
    on top for everyone (polyglotic-hq 293: English and Chinese first made
    the app look as if it were only for them)."""
    first = [c for c in (own_languages() if own is None else own) if c in _NAMES]
    rest = sorted((c for c in _NAMES if c not in first), key=language_name)
    return [Language(c) for c in [*first, *rest]]


def not_offered_note() -> str:
    """Why Mongolian and Kazakh can't be picked (#40)."""
    return _tr(_NOT_OFFERED_NOTE)


def taken_off(codes: Iterable[str]) -> tuple[str, ...]:
    """Those of `codes` that were offered once and aren't now (#40), each
    once, in order."""
    return tuple(dict.fromkeys(c for c in codes if c in _TAKEN_OFF and c not in _NAMES))


def taken_off_note(codes: Iterable[str]) -> str:
    """Home's notice for saved languages taken off (#40), by name."""
    names = name_list(_tr(_TAKEN_OFF[c]) for c in taken_off(codes))
    return _tr(_TAKEN_OFF_NOTE).format(languages=names)


# Languages dictation can be set to that aren't caption languages: the
# speech model hears them, the translator isn't offered them (283)
_HEARD_ONLY = {
    "sv": QT_TRANSLATE_NOOP("Languages", "Swedish"),
    "da": QT_TRANSLATE_NOOP("Languages", "Danish"),
    "fi": QT_TRANSLATE_NOOP("Languages", "Finnish"),
    "fa": QT_TRANSLATE_NOOP("Languages", "Persian"),
    "el": QT_TRANSLATE_NOOP("Languages", "Greek"),
    "hu": QT_TRANSLATE_NOOP("Languages", "Hungarian"),
    "mk": QT_TRANSLATE_NOOP("Languages", "Macedonian"),
    "ro": QT_TRANSLATE_NOOP("Languages", "Romanian"),
}
# Chinese dictation says which characters it types (the server's scripts)
_DICTATED = {
    "zh": QT_TRANSLATE_NOOP("Languages", "Mandarin (Simplified characters)"),
    "yue": QT_TRANSLATE_NOOP("Languages", "Cantonese (Hong Kong characters)"),
}


def dictation_language_name(code: str) -> str:
    """A language dictation can be set to, by name - Chinese with the
    characters it types: "Mandarin (Simplified characters)"."""
    name = _DICTATED.get(code) or _NAMES.get(code) or _HEARD_ONLY.get(code)
    return _tr(name) if name else code


def dictation_choices(
    codes: Iterable[str], own: Sequence[str] | None = None
) -> list[tuple[str, str]]:
    """`codes` (the languages dictation can be set to) as (code, name): the
    learner's own first - `own`, else Windows' (`own_languages`), Chinese
    in either script as Mandarin - then the rest by name (293)."""
    offered = list(codes)
    mine = own_languages() if own is None else own
    first = list(dict.fromkeys(c.split("-")[0] for c in mine))
    first = [c for c in first if c in offered]
    rest = sorted((c for c in offered if c not in first), key=dictation_language_name)
    return [(c, dictation_language_name(c)) for c in [*first, *rest]]


def learned_name(code: str) -> str:
    """A language learned, by name (Learning, the lookup's "Learn it too?"):
    Chinese - not "Chinese (Simplified)": both scripts are learned together
    - English, or a caption language's name."""
    tr = QCoreApplication.translate
    if code == "zh":
        return tr("LearningLanguage", "Chinese")
    if code == "en":
        return tr("LearningLanguage", "English")
    return language_name(code)


# Windows' tags for Traditional Chinese, by script or by region (as
# `ui.interface_language` reads them), and its codes that aren't ours
_TRADITIONAL_TAGS = ("zh-hant", "zh-tw", "zh-hk", "zh-mo")
_WINDOWS_CODES = {"fil": "tl"}


def caption_language_of(tag: str) -> str | None:
    """The caption language a Windows language tag ("zh-Hant-TW", "en-AU",
    "fil-PH") is read in - "zh-hant", "en", "tl" - or None if it isn't one
    captions are translated into."""
    tag = tag.replace("_", "-").lower()
    if tag.startswith(_TRADITIONAL_TAGS):
        code = "zh-hant"
    else:
        base = tag.split("-")[0]
        code = _WINDOWS_CODES.get(base, base)
    return code if code in _NAMES else None


def own_targets(windows_languages: Iterable[str]) -> list[str]:
    """The caption languages the learner reads: Windows' display languages
    (in the user's order) that captions are translated into, each once."""
    found = (caption_language_of(tag) for tag in windows_languages)
    return list(dict.fromkeys(code for code in found if code))
