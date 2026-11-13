"""What a caption window marks in its rows, drawn at paint time - never
laid out (decision 0031): Learning's highlights and word links, as today's
overlay shows them.

- **Saved words** in their category's colour - on live captions too.
- **Unfamiliar words** (the learner's word introductions: none, a few per
  caption or every new word) and **words in the deck**, dotted
  underneath - on finished captions only (a live update keeps changing).
- These three only on rows in the language being learned (`learns`): the
  learner's dictionary finds its words in other languages too - the
  English one 38 % of a Spanish line's (polyglotic-hq 174) - so a Spanish
  row showed English "unfamiliar" marks under de, el, que. A translation
  row in the learned language keeps its marks.
- **Word links** (the Look's "Word links": colours, or arrows), each
  linked word underlined in its link's colour.
- Nothing on Quick preview's provisional line.

A line's marks are worked out once, when it is first painted, and kept
while its rows stay the same. A Learning action on one entry (the lookup's
Add to deck, Known, Save to, Remove) forgets only the lines holding it
(`forget`), and the window repaints only those; any other Learning change
(the level, the Words page, another device) forgets them all. Exposures,
which change with every finished caption, don't: a caption keeps the
highlights it was shown with (as today).

Links "On hover" are the caption window's: the hovered word and its
counterpart, tinted. Not yet: the curves between rows for "Arrows" -
underlined in their link's colour for now. Holds caption text: never log
it.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from PySide6.QtGui import QColor, QTextCharFormat

from polyglotic_desktop.core.learning.highlights import WordIntroductions
from polyglotic_desktop.core.learning.saved_words import SavedSpan
from polyglotic_desktop.core.learning.vocabulary import Changed
from polyglotic_desktop.core.listening.display import LIVE_TRAIL, WordLinks
from polyglotic_desktop.core.shared import EntryId
from polyglotic_desktop.ui_next.caption_layout import LINK_MARK, Mark
from polyglotic_desktop.ui_next.views.captions import Line
from polyglotic_desktop.ui_next.views.lookup import Learner

LINK_COLORS = (
    "#ff9f43",
    "#b388ff",
    "#4dd0e1",
    "#ff6e9c",
    "#a5d66f",
    "#5c9dff",
    "#ff5252",
    "#3ddc97",
    "#e040fb",
    "#c8925a",
)
"""A colour per link, not a text colour (white, yellow and saved words'
colours already mean something) - today's, ordered so neighbours are far
apart in hue."""
UNFAMILIAR = "#ffd27a"
"""Dots under a word new to the learner."""
IN_DECK = "#7ee0a8"
"""Dashes under a word in the deck: a different shape, not only a different
colour, so the two read apart for a colour-blind learner (135, 2026-11-07)."""
KEPT = 400
"""Lines whose marks are kept: more than a caption window's 150."""


@dataclass(frozen=True, slots=True)
class _Kept:
    """A line's marks while its rows stay the same, and what they rest on:
    the entries in it (its words, its saved words) and its text."""

    rows: object
    marks: list[list[Mark]]
    entries: frozenset[EntryId]
    text: str


class CaptionMarks:
    """A caption window's marks, by line and row: `marks(line, row)`."""

    def __init__(self, learner: Learner | None) -> None:
        self.learner = learner
        self.word_links = WordLinks.OFF
        self.introductions = WordIntroductions.A_FEW
        self._kept: dict[int, _Kept] = {}
        self._formats: dict[tuple[str, str, int], QTextCharFormat] = {}

    def set_look(self, word_links: WordLinks, introductions: WordIntroductions) -> None:
        if (word_links, introductions) != (self.word_links, self.introductions):
            self.word_links, self.introductions = word_links, introductions
            self._kept.clear()

    def learning_changed(self, what: str) -> bool:
        """Statuses, saved words or the level changed: True if what shows
        may have (the window repaints); not for exposures."""
        if what == Changed.EXPOSURES.value:
            return False
        self._kept.clear()
        return True

    def forget(self, entry_id: EntryId, texts: Collection[str]) -> set[int]:
        """One entry changed (`texts`: its forms - a saved word is found in
        a line by them too): the marks of the lines holding it are worked
        out again when next painted. The keys of those lines."""
        found = {
            key
            for key, kept in self._kept.items()
            if entry_id in kept.entries or any(t and t in kept.text for t in texts)
        }
        for key in found:
            del self._kept[key]
        return found

    def __call__(self, line: Line, row: int) -> Sequence[Mark]:
        found = self._kept.get(line.key)
        if found is None or found.rows is not line.rows:
            if len(self._kept) > KEPT:
                self._kept.clear()
            found = self._marks(line)
            if self.learner is None or self.learner.ready:
                self._kept[line.key] = found  # else marked again once it is
        rows = found.marks
        return rows[row] if row < len(rows) else ()

    def _marks(self, line: Line) -> _Kept:
        marks: list[list[Mark]] = [[] for _ in line.rows]
        text = "\n".join(row.text for row in line.rows)
        if line.provisional:
            return _Kept(line.rows, marks, frozenset(), text)
        learner = self.learner
        entries: set[EntryId] = set()
        if learner is not None and learner.ready:  # else: no Learning marks yet
            self._learning(line, learner, marks, entries)
        if self.word_links in (WordLinks.COLOURS, WordLinks.ARROWS):
            for index, row in enumerate(line.rows):
                for linked in row.links:
                    color = LINK_COLORS[linked.link % len(LINK_COLORS)]
                    marks[index].append(
                        (
                            linked.start,
                            linked.end,
                            self._format("link", color, linked.link),
                        )
                    )
        return _Kept(line.rows, marks, frozenset(entries), text)

    def _learning(
        self,
        line: Line,
        learner: Learner,
        marks: list[list[Mark]],
        entries: set[EntryId],
    ) -> None:
        vocabulary = learner.vocabulary
        texts = [row.text.removesuffix(LIVE_TRAIL) for row in line.rows]
        learned = [learner.learns(row.language) for row in line.rows]
        texts = [
            text if ours else "" for text, ours in zip(texts, learned, strict=True)
        ]
        words = [learner.words_in(text) for text in texts]
        entries.update(w.entry.entry_id for found in words for w in found)

        def saved(index: int, spans: Sequence[SavedSpan]) -> None:
            for span in spans:
                entries.add(span.entry_id)
                found = vocabulary.saved_word(span.entry_id)
                category = vocabulary.category(found.category_id) if found else None
                if category is not None:
                    marks[index].append(
                        (span.start, span.end, self._format("saved", category.color))
                    )

        if line.live:  # saved words only: a live update keeps changing
            for index, (text, found) in enumerate(zip(texts, words, strict=True)):
                saved(index, vocabulary.saved_spans(text, found))
            return
        shown = vocabulary.highlights(
            list(zip(texts, words, strict=True)), self.introductions
        )
        for index, highlights in enumerate(shown):
            for word in highlights.unfamiliar:
                marks[index].append(
                    (word.start, word.end, self._format("dotted", UNFAMILIAR))
                )
            for word in highlights.in_deck:  # dashes: told apart without colour
                marks[index].append(
                    (word.start, word.end, self._format("dashed", IN_DECK))
                )
            saved(index, highlights.saved)

    def _format(self, kind: str, color: str, link: int = 0) -> QTextCharFormat:
        found = self._formats.get((kind, color, link))
        if found is not None:
            return found
        format_ = QTextCharFormat()
        if kind == "saved":
            format_.setForeground(QColor(color))
        elif kind == "link":  # drawn by the layout, below the descenders (F14)
            format_.setProperty(LINK_MARK, link)  # its number: Arrows' ends meet
            format_.setUnderlineColor(QColor(color))
        else:
            format_.setUnderlineStyle(
                {
                    "dotted": QTextCharFormat.UnderlineStyle.DotLine,
                    "dashed": QTextCharFormat.UnderlineStyle.DashUnderline,
                }.get(kind, QTextCharFormat.UnderlineStyle.SingleUnderline)
            )
            format_.setUnderlineColor(QColor(color))
        self._formats[(kind, color, link)] = format_
        return format_
