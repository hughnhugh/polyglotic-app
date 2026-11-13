"""Learning, a page of the main window (polyglotic-hq 262; 248's IA.md,
sections 3 and 3.6; the user's F19, F29 and F30): what you're learning,
what each language's dictionary can do, your level, and which words
captions point out - each said in words, not left to guess.

Top to bottom, in the pages' column:
- **a card per language being learned** (`views.learning.cards`): its
  dictionary's tier - full, basic or none yet - and what that gives; a
  full dictionary's level, with "Change your level" for the one in use
  (and what a level does: words at or below it count as known, nothing
  is tested); "Use X instead" for another full dictionary (one at a time
  for now, from the next start, each keeping its words); "Stop learning"
  for the others;
- **Learn another language** - every caption language, by name, each
  saying what it gets (none pinned on top: 293);
- **Word introductions** - Off · A few per caption · Every new word
  (`core.learning.highlights.WordIntroductions`), what each does, a
  caption drawn with the marks, and where the words go;
- **Words and Anki** - Words, and the site's help on importing;
- **Your learning data** - Account's "Delete learning data…", the same
  command.

The page only shows and asks: `main` hands over the cards and the choice,
and turns what's asked (`languages_wanted`, `introductions_chosen`,
`change_level_wanted`, `words_wanted`) into the settings and today's level
picker. Holds no words or caption text: its sample caption is the app's
own.
"""

from collections.abc import Sequence

from PySide6.QtCore import QT_TRANSLATE_NOOP, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.core.learning.highlights import WordIntroductions
from polyglotic_desktop.core.learning.languages import (
    LearningLanguages,
    Tier,
    learned_code,
    tier_of,
)
from polyglotic_desktop.core.shared.papers import HELP_ANKI
from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.caption_layout import CJK_FAMILIES, LATIN_FAMILIES
from polyglotic_desktop.ui_next.caption_marks import IN_DECK, UNFAMILIAR
from polyglotic_desktop.ui_next.controls import Card, Segmented, label, page_button
from polyglotic_desktop.ui_next.home import OneClick, Page
from polyglotic_desktop.ui_next.languages import learned_name, target_languages
from polyglotic_desktop.ui_next.views.learning import LanguageCard, offered
from polyglotic_desktop.ui_next.views.words import LevelLine


def _tr(text: str) -> str:
    return QApplication.translate("Learning", text)


def learnable() -> list[str]:
    """Every language that can be learned, by name: each caption language's
    learned code, once (Simplified and Traditional Chinese are one) - none
    pinned on top (polyglotic-hq 293); each says what its dictionary gives."""
    codes = dict.fromkeys(learned_code(c) for c in target_languages(own=()))
    return sorted(codes, key=learned_name)


def tier_name(tier: Tier) -> str:
    return {
        Tier.FULL: _tr("Full dictionary"),
        Tier.BASIC: _tr("Basic dictionary"),
        Tier.NONE: _tr("No dictionary yet"),
    }[tier]


def what_it_gives(code: str, tier: Tier, pack_here: bool = False) -> str:
    """What learning `code` gives, by its dictionary's tier - the line under
    its name (polyglotic-hq 248, sections 3.1 and 3.3)."""
    if code == "zh":
        return _tr(
            "CC-CEDICT, with pinyin. Lookups, your level, word introductions, "
            "the words you hear and save, and an Anki deck."
        )
    if code == "en":
        return _tr(
            "ECDICT, with meanings in Chinese. Lookups, your level, word "
            "introductions, the words you hear and save, and an Anki deck."
        )
    name = learned_name(code)
    if tier is Tier.BASIC and pack_here:
        return _tr(
            "From open data, meanings not checked by a person. Lookups in "
            "{language} captions work, marked basic; your level, word "
            "introductions and saved words come later."
        ).format(language=name)
    if tier is Tier.BASIC:
        return _tr(
            "Coming: a basic dictionary from open data, downloaded when it's "
            "ready. Until then captions and translation work, without lookups."
        )
    return _tr(
        "Captions and translation work; there are no lookups or word "
        "introductions yet. We'll add a dictionary when one passes our check."
    )


def level_text(line: LevelLine) -> str:
    """A language's level, in Words' words (the same translations)."""
    tr = QApplication.translate
    if not line.picked:
        return tr("Words", "Not set yet - words count as known up to a middle level.")
    scheme = tr("Words", line.scheme)  # the schemes' names are Words'
    if not line.level:
        return tr("Words", "{scheme}: just starting").format(scheme=scheme)
    return tr("Words", "{scheme}: {level}").format(scheme=scheme, level=line.level)


INTRODUCTION_LINES = {
    WordIntroductions.OFF: QT_TRANSLATE_NOOP(
        "Learning",
        "No new words are pointed out. Words you've saved or put in your deck "
        "still show in their colours.",
    ),
    WordIntroductions.A_FEW: QT_TRANSLATE_NOOP(
        "Learning",
        "The commonest new words and the ones you keep hearing - at most about "
        "one word in twenty, and two a line.",
    ),
    WordIntroductions.EVERY: QT_TRANSLATE_NOOP(
        "Learning",
        "Every word that's new to you. Busy in fast speech; good for slow, "
        "careful listening.",
    ),
}


def introductions_line(choice: WordIntroductions) -> str:
    return _tr(str(INTRODUCTION_LINES[choice]))


SAMPLES: dict[bool, tuple[tuple[str, str], ...]] = {
    # (word, mark): "new" shows with a few or every; "more" with every
    True: (
        ("我今天去", ""),
        ("超市", "new"),
        ("买了", ""),
        ("榴莲", "more"),
        ("和", ""),
        ("酸奶", "deck"),
    ),
    False: (
        ("The ", ""),
        ("quarterly", "new"),
        (" figures look ", ""),
        ("promising", "deck"),
        (", the ", ""),
        ("analysts", "more"),
        (" said", ""),
    ),
}
"""The sample caption, Chinese (True) or English: each piece and its mark -
"new" shows with a few or every, "more" with every, "deck" always."""


class IntroductionSample(QWidget):
    """A caption as a caption window draws it, with the marks the choice
    gives: new words dotted in yellow, a word in the deck dashed in green
    (`caption_marks`' colours and shapes). The app's own sentence, in the
    language being learned."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("learning.sample")
        self.chinese = True
        self.choice = WordIntroductions.A_FEW
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(style.px(52))

    def show_choice(self, choice: WordIntroductions, chinese: bool) -> None:
        self.choice, self.chinese = choice, chinese
        self.update()

    def _font(self) -> QFont:
        font = QFont()
        families = CJK_FAMILIES if self.chinese else LATIN_FAMILIES
        font.setFamilies(list(families))
        font.setPixelSize(style.px(20))
        return font

    def _marked(self, mark: str) -> str:
        if mark == "deck":
            return "deck"
        shown = {
            WordIntroductions.OFF: (),
            WordIntroductions.A_FEW: ("new",),
            WordIntroductions.EVERY: ("new", "more"),
        }[self.choice]
        return "new" if mark in shown else ""

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 12, 16, 235))  # a caption window's panel
        painter.drawRoundedRect(panel, 8, 8)
        font = self._font()
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        x = float(style.px(14))
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2
        for text, mark in SAMPLES[self.chinese]:
            width = metrics.horizontalAdvance(text)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(x, 0, width + 2, self.height()),
                Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            shown = self._marked(mark)
            if shown:
                pen = QPen(QColor(UNFAMILIAR if shown == "new" else IN_DECK))
                pen.setWidthF(max(1.5, style.px(2)))
                pen.setStyle(
                    Qt.PenStyle.DotLine if shown == "new" else Qt.PenStyle.DashLine
                )
                painter.setPen(pen)
                y = baseline + metrics.descent() + 1
                painter.drawLine(int(x), int(y), int(x + width), int(y))
            x += width
        painter.end()


class LanguageCardView(Card):
    """One language's card (`views.learning.LanguageCard`)."""

    def __init__(self, card: LanguageCard, running: str | None) -> None:
        name = learned_name(card.code)
        super().__init__(name)
        self.setObjectName("Card")
        self.code = card.code
        self.setAccessibleName(name)
        assert self.title is not None
        heading = QHBoxLayout()
        heading.setSpacing(10)
        self.column.removeWidget(self.title)
        heading.addWidget(self.title)
        tier = label(tier_name(card.tier), "Dim")
        heading.addWidget(tier)
        heading.addStretch(1)
        self.column.insertLayout(0, heading)
        self.add(
            label(
                what_it_gives(card.code, card.tier, card.pack_here), "Faint", wrap=True
            )
        )

        self.change_level: QPushButton | None = None
        if card.level is not None:
            line = QHBoxLayout()
            line.setSpacing(12)
            words = QVBoxLayout()
            words.setSpacing(2)
            words.addWidget(label(_tr("Your level"), "RowTitle"))
            level = label(level_text(card.level), wrap=True)
            level.setObjectName(f"learning.{card.code}.level")
            words.addWidget(level)
            line.addLayout(words, 1)
            if card.can_change_level:
                self.change_level = _button(
                    _tr("Change your level"), f"learning.{card.code}.change_level"
                )
                line.addWidget(self.change_level)
            self.add(line)
            if card.can_change_level:
                self.add(
                    label(
                        _tr(
                            "Words at or below your level count as known, and the "
                            "next ones are pointed out. Nothing is tested: a click "
                            "on any word corrects it."
                        ),
                        "Faint",
                        wrap=True,
                    )
                )
            elif card.tier is Tier.FULL:
                self.add(
                    label(
                        _tr("You can change it while {language} is in use.").format(
                            language=learned_name(card.code)
                        ),
                        "Faint",
                        wrap=True,
                    )
                )

        said = ""
        if card.starts_next:
            said = _tr(
                "In use from the next time Polyglotic starts. One full dictionary "
                "is in use at a time for now; each language keeps its words."
            )
        elif card.stops_next:
            said = _tr("In use until Polyglotic starts again; its words are kept.")
        elif card.can_switch:
            said = _tr(
                "One full dictionary is in use at a time for now. Each language "
                "keeps its words."
            )
        if said:
            note = label(said, "Dim", wrap=True)
            self.add(note)

        self.switch: QPushButton | None = None
        self.stop: QPushButton | None = None
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        if card.can_switch:
            text = (
                _tr("Keep using {language}")
                if card.stops_next
                else _tr("Use {language} instead")
            )
            self.switch = _button(
                text.format(language=name), f"learning.{card.code}.switch"
            )
            self.switch.setToolTip(_tr("From the next time Polyglotic starts"))
            buttons.addWidget(self.switch)
        if not card.main:
            self.stop = _button(
                _tr("Stop learning {language}").format(language=name),
                f"learning.{card.code}.stop",
            )
            self.stop.setProperty("kind", "ghost")
            self.stop.setToolTip(_tr("Its words are kept - delete them on Account"))
            buttons.addWidget(self.stop)
        if self.switch is not None or self.stop is not None:
            self.add(buttons)


class LearningPage(Page):
    """What you're learning and how (polyglotic-hq 262)."""

    change_level_wanted = Signal()
    """The language in use's "Change your level": `main` opens the picker."""
    languages_wanted = Signal(object)
    """The languages being learned, changed (`LearningLanguages`)."""
    introductions_chosen = Signal(object)
    """Word introductions chosen (`WordIntroductions`)."""
    words_wanted = Signal()
    """"Open Words"."""

    def __init__(self, delete_learning: QAction | None = None) -> None:
        """`delete_learning`: Account's "Delete learning data…" - the same
        command, on both pages."""
        super().__init__(_tr("Learning"))
        self.languages = LearningLanguages()
        self.running: str | None = None
        self._shown: tuple[object, ...] | None = None
        """What `show_learning` was last given: the same again changes nothing."""
        intro = label(
            _tr(
                "For each language you learn, Polyglotic keeps your words: lookups "
                "use its dictionary, your level estimates which words you know, "
                "and captions point out new ones. Captions and translation work "
                "in every language, whatever you choose here."
            ),
            "PageSubtitle",
            wrap=True,
        )
        self.content.addWidget(intro)

        self.cards_column = QWidget()
        self.cards_column.setObjectName("learning.languages")
        self.cards_layout = QVBoxLayout(self.cards_column)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(16)
        self.content.addWidget(self.cards_column)
        self.cards: list[LanguageCardView] = []
        self.none_yet = Card(
            _tr("Languages you're learning"),
            _tr(
                "None yet. Pick one below for lookups, your level and word "
                "introductions."
            ),
        )
        self.none_yet.hide()
        self.cards_layout.addWidget(self.none_yet)

        another = Card(_tr("Learn another language"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.choices = QComboBox()
        self.choices.setObjectName("learning.another")
        self.choices.setAccessibleName(_tr("Learn another language"))
        # none chosen until the learner picks: the list is by name, and its
        # first language isn't a suggestion (293)
        self.choices.setPlaceholderText(_tr("Choose a language"))
        self.choices.currentIndexChanged.connect(self._chosen)
        row.addWidget(self.choices, 1)
        self.add = _button(_tr("Learn it"), "learning.add")
        # a double-click's second click is let go: after the first, the list
        # moves on to the next language, and the second added that one too
        # (269: Japanese after English)
        self._add_once = OneClick()
        self._add_once.watch(self.add)
        self.add.clicked.connect(lambda: self._add_once(self._add))
        row.addWidget(self.add)
        another.add(row)
        self.chosen_gives = label("", "Faint", wrap=True)
        another.add(self.chosen_gives)
        self.another = another
        self.content.addWidget(another)

        introductions = Card(
            _tr("Word introductions"),
            _tr(
                "Captions point out words that are probably new to you, so you "
                "notice them as you hear them. They're guessed from your level; "
                "a click on any word corrects it."
            ),
        )
        self.introductions = Segmented(
            [
                (WordIntroductions.OFF, _tr("Off")),
                (WordIntroductions.A_FEW, _tr("A few per caption")),
                (WordIntroductions.EVERY, _tr("Every new word")),
            ],
            WordIntroductions.A_FEW,
        )
        self.introductions.setObjectName("learning.introductions")
        self.introductions.setAccessibleName(_tr("Word introductions"))
        self.introductions.changed.connect(self._introductions_chosen)
        introductions.add(_left(self.introductions))
        self.introductions_said = label("", "Dim", wrap=True)
        introductions.add(self.introductions_said)
        self.sample = IntroductionSample()
        introductions.add(self.sample)
        introductions.add(
            label(
                _tr(
                    "Dotted yellow: a word new to you. Dashed green: a word in your "
                    "deck. A saved word takes its category's colour. Only finished "
                    "captions in a language you're learning are marked."
                ),
                "Faint",
                wrap=True,
            )
        )
        introductions.add(
            label(
                _tr(
                    "Where they go: hear a word a few times and it joins Words you "
                    "keep hearing, on Words. Add it to your deck there or from its "
                    "lookup, and it goes into your next Anki export."
                ),
                "Dim",
                wrap=True,
            )
        )
        self.content.addWidget(introductions)

        words = Card(
            _tr("Words and Anki"),
            _tr(
                "Your deck, your saved words and the words you keep hearing are on "
                "Words. Each language exports a deck of its own."
            ),
        )
        self.open_words = _button(_tr("Open Words"), "learning.open_words")
        self.open_words.clicked.connect(self.words_wanted)
        words.add(
            _right(
                self.open_words,
                page_button(
                    _tr("How to import into Anki"), HELP_ANKI, "learning.anki_help"
                ),
            )
        )
        self.content.addWidget(words)

        data = Card(
            _tr("Your learning data"),
            _tr(
                "The words you look up, save and mark are kept on this PC, and on "
                "our server as dictionary words and times. You can delete them, "
                "in every language you learn - the same as on Account."
            ),
        )
        if delete_learning is not None:
            data.add(_right(_action_button(delete_learning)))
        self.content.addWidget(data)
        self.content.addStretch(1)
        self._show_choices()
        self._show_introductions(WordIntroductions.A_FEW)

    # -- what it shows -------------------------------------------------------------------

    def show_learning(
        self,
        languages: LearningLanguages,
        cards: Sequence[LanguageCard],
        introductions: WordIntroductions,
        running: str | None = None,
        chinese: bool = True,
    ) -> None:
        """The languages being learned (`cards`, from `views.learning`), the
        word introductions chosen, and the language in use now (`running`;
        the sample caption is in Chinese or English by `chinese`). Asked
        again with the same (any setting changed): nothing is rebuilt."""
        shown = (languages, tuple(cards), introductions, running, chinese)
        if shown == self._shown:
            return
        self._shown = shown
        self.languages, self.running = languages, running
        for old in self.cards:
            old.hide()
            self.cards_layout.removeWidget(old)
            old.deleteLater()
        self.cards = []
        for n, card in enumerate(cards):
            view = LanguageCardView(card, running)
            self.cards_layout.insertWidget(n, view)  # parented before it shows
            if view.change_level is not None:
                view.change_level.clicked.connect(self.change_level_wanted)
            if view.switch is not None:
                view.switch.clicked.connect(
                    lambda _=False, c=card.code: self._wanted(
                        self.languages.switched_to(c)
                    )
                )
            if view.stop is not None:
                view.stop.clicked.connect(
                    lambda _=False, c=card.code: self._wanted(self.languages.stopped(c))
                )
            self.cards.append(view)
        self.none_yet.setVisible(not cards)
        self._show_choices()
        self.introductions.set_value(introductions)
        self._show_introductions(introductions, chinese)

    def card(self, code: str) -> LanguageCardView | None:
        return next((c for c in self.cards if c.code == code), None)

    def _show_choices(self) -> None:
        """Learn another language: those not learned, by name, each named
        with its tier."""
        blocked = self.choices.blockSignals(True)
        wanted = self.choices.currentData()
        self.choices.clear()
        for code in offered(self.languages, learnable()):
            self.choices.addItem(
                _tr("{language} - {tier}").format(
                    language=learned_name(code), tier=tier_name(tier_of(code))
                ),
                code,
            )
        self.choices.setCurrentIndex(self.choices.findData(wanted))  # -1: none
        self.choices.blockSignals(blocked)
        self.another.setVisible(self.choices.count() > 0)
        self._chosen()

    def _chosen(self, _index: int = 0) -> None:
        code = self.choices.currentData()
        self.chosen_gives.setText(
            what_it_gives(code, tier_of(code)) if isinstance(code, str) else ""
        )
        self.add.setEnabled(isinstance(code, str))  # nothing to learn yet

    def _show_introductions(
        self, choice: WordIntroductions, chinese: bool | None = None
    ) -> None:
        self.introductions_said.setText(introductions_line(choice))
        self.sample.show_choice(
            choice, self.sample.chinese if chinese is None else chinese
        )

    # -- what it asks --------------------------------------------------------------------

    def _add(self) -> None:
        code = self.choices.currentData()
        if isinstance(code, str):
            self._wanted(self.languages.added(code))

    def _wanted(self, languages: LearningLanguages) -> None:
        if languages != self.languages:
            self.languages_wanted.emit(languages)

    def _introductions_chosen(self, choice: object) -> None:
        if isinstance(choice, WordIntroductions):
            self._show_introductions(choice)
            self.introductions_chosen.emit(choice)


def _button(text: str, name: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _action_button(action: QAction) -> QPushButton:
    """A button showing `action` (Account's): its text, and whether it
    shows and works - as Account's own button follows it."""
    button = _button(action.text(), f"learning.{action.objectName()}")

    def follow() -> None:
        button.setText(action.text())
        button.setVisible(action.isVisible())
        button.setEnabled(action.isEnabled())

    button.clicked.connect(action.trigger)
    action.changed.connect(follow)
    follow()
    return button


def _left(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(widget)
    row.addStretch(1)
    return row


def _right(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    return row
