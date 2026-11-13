"""Lookup context: the line a word was looked up in, and its translation.

From the proof of concept's `ui/lookup.py` (`context_for`), out of Qt and
by language code rather than by script. A saved word keeps it as its
source sentence and that sentence's translation - the user's own data,
kept on this PC (never sent: the server gets entry IDs and times only).
"""

from collections.abc import Mapping
from dataclasses import dataclass

_CONTINUED = " …"  # how a cut-off overlay row ends


@dataclass(frozen=True)
class LookupContext:
    sentence: str  # the line the word was in
    translation: str = ""  # that line in another language, if any


def is_chinese(language: str) -> bool:
    """Mandarin in any script, or Cantonese (protocol.md's codes)."""
    return language == "zh" or language.startswith("zh-") or language == "yue"


def lookup_context(line: str, versions: Mapping[str, str]) -> LookupContext:
    """The lookup context of a word in `line`, one of `versions` - the
    caption's (or the clause row's) text by language code, what was said
    first, then its translations. The translation paired with it: for a
    Chinese line, the English version if there is one, else the first
    that isn't Chinese; for any other line, a Chinese version if there is
    one, else the first other version."""
    sentence = line.removesuffix(_CONTINUED)
    own = next((lang for lang, text in versions.items() if text == sentence), None)
    others = [
        (lang, text)
        for lang, text in versions.items()
        if text and text != sentence and lang != own
    ]
    if own is not None and is_chinese(own):
        preferred = [text for lang, text in others if lang == "en"] + [
            text for lang, text in others if not is_chinese(lang)
        ]
    else:
        preferred = [text for lang, text in others if is_chinese(lang)]
    preferred += [text for _, text in others]
    return LookupContext(sentence, preferred[0] if preferred else "")
