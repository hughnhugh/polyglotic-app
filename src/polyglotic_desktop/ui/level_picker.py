"""The level picker: at first run (and any time after), the learner picks
their level - an HSK 3.0 level, or an English frequency band - and words
at or below it count as known (polyglotic-hq MVP.md, "Known words").

Chinese learners choose between the two HSK 3.0 documents, the 2025 exam
syllabus first (the user's default, 2026-11-04); English learners have the
frequency bands. "Just starting" is level 0: nothing known yet. The choice
sets Learning's level curve (`Vocabulary.set_level`); the learner's own
statuses are kept.
"""

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from polyglotic_desktop.core.lexicon.entries import (
    DEFAULT_CHINESE_SCHEME,
    ENGLISH_FREQUENCY,
    HSK_2021,
    HSK_2025,
    LevelScheme,
)
from polyglotic_desktop.core.shared import Level
from polyglotic_desktop.ui.first_run import add_back
from polyglotic_desktop.ui.widgets import TextDialog


class LevelPicker(TextDialog):
    def __init__(
        self, chinese: bool, current: Level | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LevelPicker")
        self.setWindowTitle(self.tr("Your level"))
        self.setMinimumWidth(460)
        self._schemes = [HSK_2025, HSK_2021] if chinese else [ENGLISH_FREQUENCY]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title = QLabel(self.tr("What's your level?"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel(
            self.tr(
                "Words at or below your level count as known, so captions mark "
                "only the words you're likely to be learning. You can change it "
                "any time, and correct any word with one click."
            )
        )
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.scheme = QComboBox()
        for scheme in self._schemes:
            self.scheme.addItem(self._scheme_name(scheme), scheme.id)
        # in the dialog before it's shown: shown first, it was a window of its
        # own for a moment - 803 ms at a first run (polyglotic-hq 273)
        layout.addWidget(self.scheme)
        self.scheme.setVisible(len(self._schemes) > 1)
        self._choices = QVBoxLayout()
        self._choices.setSpacing(4)
        layout.addLayout(self._choices)
        self._group = QButtonGroup(self)
        self._buttons: list[QRadioButton] = []

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.back = add_back(self, buttons)  # at the first run: the language
        layout.addWidget(buttons)

        start = current or Level(
            (DEFAULT_CHINESE_SCHEME if chinese else ENGLISH_FREQUENCY).id, 0
        )
        index = max(0, self.scheme.findData(start.scheme))
        self.scheme.setCurrentIndex(index)
        self._fill(start.value)
        self.scheme.currentIndexChanged.connect(lambda _: self._fill(self.value()))

    def _scheme_name(self, scheme: LevelScheme) -> str:
        return {
            HSK_2025.id: self.tr(
                "HSK 3.0 - the 2025 exam syllabus (what the exam tests)"
            ),
            HSK_2021.id: self.tr("HSK 3.0 - the 2021 standard"),
            ENGLISH_FREQUENCY.id: self.tr("The most common English words"),
        }.get(scheme.id, scheme.name)

    def _label(self, scheme: LevelScheme, value: int) -> str:
        if value == 0:
            return self.tr("Just starting - mark every word as new")
        words = scheme.words_at(value)
        name = scheme.levels[value - 1]
        if scheme.cutoffs:
            return self.tr("I know most of the {count} most common words").format(
                count=name
            )
        if words:
            return self.tr("HSK {level} - about {count} words").format(
                level=name, count=QLocale().toString(words)
            )
        return self.tr("HSK {level}").format(level=name)

    def _fill(self, value: int) -> None:
        for button in self._buttons:
            self._group.removeButton(button)
            button.deleteLater()
        self._buttons = []
        scheme = self._schemes[max(0, self.scheme.currentIndex())]
        for n in range(len(scheme.levels) + 1):
            button = QRadioButton(self._label(scheme, n))
            button.setObjectName(f"level.{n}")
            self._group.addButton(button, n)
            self._choices.addWidget(button)
            self._buttons.append(button)
        self._buttons[min(value, len(self._buttons) - 1)].setChecked(True)

    def value(self) -> int:
        return max(0, self._group.checkedId())

    def level(self) -> Level:
        """The level chosen."""
        return Level(str(self.scheme.currentData()), self.value())
