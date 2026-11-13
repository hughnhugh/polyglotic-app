"""Settings > Captions > Lab: experimental caption settings, for the user
and the testers to tune by feel (polyglotic-hq 284; the values and their
measured ranges are `views.lab`'s). Marked as experimental, with its own
preview - the look's, so a change shows beside the control that made it -
and "Reset the lab".

Every control changes the running caption windows and both previews at
once (the look's view, `LookView.set_lab`), and is saved once it settles,
as the look is (`main.Panels`). A card of its own, in a file of its own,
so other sections of the page don't meet it.
"""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QWidget,
)

from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.caption_layout import LINK_PX
from polyglotic_desktop.ui_next.caption_preview import CaptionPreview
from polyglotic_desktop.ui_next.controls import INSET, Row, Segmented, label
from polyglotic_desktop.ui_next.panels import Panel
from polyglotic_desktop.ui_next.views.lab import (
    ARRIVAL_GAP_RANGE,
    ARRIVAL_GAP_STEP,
    CAPTION_GAP_RANGE,
    LINK_PX_RANGE,
    LINK_PX_STEP,
    NEW_FOR_RANGE,
    NEW_FOR_STEP,
    OLDER_RANGE,
    OLDER_STEP,
    ROW_GAP_RANGE,
    SPACING_STEP,
    CaptionLab,
    Loading,
    NewFade,
    Unfinished,
)
from polyglotic_desktop.ui_next.views.panels import LookView

DEFAULT = CaptionLab()
"""The Lab untouched: each slider's own value, a notch on its scale."""


def _tr(text: str) -> str:
    return QApplication.translate("Lab", text)


class Slider(QWidget):
    """A slider over `steps` of `step` from `low`, with its value said
    beside it (`say`). `default`: the setting's own value, where the
    slider shows it - the notch nearest to it is the default itself, so
    the slider moved away and back gives the default, not its neighbour
    on the scale (polyglotic-hq 287: Older captions' 72 % isn't a
    multiple of 5 % from 45 %, and came back as 70 %)."""

    def __init__(
        self,
        name: str,
        title: str,
        low: float,
        high: float,
        step: float,
        default: float | None = None,
    ) -> None:
        super().__init__()
        self.low, self.step, self.default = low, step, default
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName(name)
        self.slider.setAccessibleName(title)
        self.slider.setRange(0, round((high - low) / step))
        self.slider.setMinimumWidth(style.px(160))
        self.shown = label("", "Dim")
        self.shown.setMinimumWidth(style.px(96))
        line.addWidget(self.slider, 1)
        line.addWidget(self.shown)

    def value(self) -> float:
        if self.default is not None and self.slider.value() == self._at(self.default):
            return self.default
        return round(self.low + self.slider.value() * self.step, 2)

    def _at(self, value: float) -> int:
        return round((value - self.low) / self.step)

    def show_value(self, value: float, text: str) -> None:
        position = self._at(value)
        if position != self.slider.value():
            blocked = self.slider.blockSignals(True)
            self.slider.setValue(position)
            self.slider.blockSignals(blocked)
        self.shown.setText(text)


def _left(control: QWidget) -> QWidget:
    """`control` at the left of a row as wide as the card."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(control)
    row.addStretch(1)
    return box


def _pixels(value: float) -> str:
    return _tr("{px} px").format(px=f"{value:g}")


def _seconds(value: float) -> str:
    return _tr("{seconds}s").format(seconds=f"{value:g}")


def _percent(value: float) -> str:
    return _tr("{percent}%").format(percent=round(value * 100))


class LabPanel(Panel):
    """The Lab's controls, bound to the look's view."""

    def __init__(self, view: LookView, parent: QWidget | None = None) -> None:
        super().__init__(
            _tr("Lab - experimental"),
            _tr(
                "Settings to try by feel. Each changes the caption windows and "
                "the preview at once. Tell us what works - they may change or go."
            ),
            parent=parent,
        )
        self.setObjectName("Card")
        self.view = view
        self.preview = CaptionPreview(view, unfinished=True)
        self.preview.setObjectName("lab.preview")
        self.add(self.preview)

        self.new_for = Slider(
            "lab.new_for",
            _tr("New captions stay bright"),
            *NEW_FOR_RANGE,
            NEW_FOR_STEP,
            DEFAULT.new_for,
        )
        self.new_for.slider.valueChanged.connect(
            lambda _: self._set(new_for=self.new_for.value())
        )
        self.add(
            Row(
                _tr("New captions stay bright"),
                _tr(
                    "How long a caption stays at full brightness after it arrives, "
                    "so several arriving together all look new. 0 s: only the "
                    "newest."
                ),
                self.new_for,
            )
        )
        self.new_fade = Segmented(
            [
                (NewFade.INSTANT, _tr("At once")),
                (NewFade.GRADUAL, _tr("Gradually")),
            ]
        )
        self.new_fade.setObjectName("lab.new_fade")
        self.new_fade.changed.connect(lambda v: self._set(new_fade=NewFade(v)))
        self.add(
            Row(
                _tr("Then it dims"),
                _tr("At once, or fading over a second and a half."),
                _left(self.new_fade),
            )
        )
        self.older = Slider(
            "lab.older", _tr("Older captions"), *OLDER_RANGE, OLDER_STEP, DEFAULT.older
        )
        self.older.slider.valueChanged.connect(
            lambda _: self._set(older=self.older.value())
        )
        self.add(
            Row(
                _tr("Older captions"),
                _tr(
                    "How bright the captions before the newest stay. 100%: as "
                    "bright as the newest. The translation dims a little less."
                ),
                self.older,
            )
        )
        self.unfinished = Segmented(
            [
                (Unfinished.AS_NOW, _tr("As now")),
                (Unfinished.SAME, _tr("Same as finished")),
                (Unfinished.DIMMER, _tr("Dimmer")),
                (Unfinished.ITALIC, _tr("Italic")),
                (Unfinished.COLOUR, _tr("Colour")),
            ]
        )
        self.unfinished.setObjectName("lab.unfinished")
        self.unfinished.changed.connect(lambda v: self._set(unfinished=Unfinished(v)))
        self.add(
            Row(
                _tr("Text still being spoken"),
                _tr(
                    "How a line that may still change looks beside finished text. "
                    "As now: Steady's and Quick preview's dim italic line, Live "
                    "updates' a little dim. Colour: the theme's blue."
                ),
                _left(self.unfinished),
            )
        )
        self.loading = Segmented(
            [
                (Loading.BAR, _tr("Bar")),
                (Loading.DOTS, _tr("Three dots")),
                (Loading.ELLIPSIS, _tr("Ellipsis")),
            ]
        )
        self.loading.setObjectName("lab.loading")
        self.loading.changed.connect(lambda v: self._set(loading=Loading(v)))
        self.add(
            Row(
                _tr("While a caption is on its way"),
                _tr(
                    "The sign under the captions that speech was heard. Ellipsis: "
                    "the line still being spoken ends in one; with none yet, one "
                    "stands where the bar would."
                ),
                _left(self.loading),
            )
        )
        self.link_px = Slider(
            "lab.link_px", _tr("Underline thickness"), *LINK_PX_RANGE, LINK_PX_STEP
        )
        self.link_px.slider.valueChanged.connect(
            lambda _: self._set(link_px=self.link_px.value())
        )
        self.add(
            Row(
                _tr("Underline thickness"),
                _tr(
                    "A word link's underline, finer than Word links' Thin, Medium "
                    "and Thick. Picking one of those there again puts it back."
                ),
                self.link_px,
            )
        )
        self.row_gap = Slider(
            "lab.row_gap", _tr("Space above the translation"), *ROW_GAP_RANGE,
            SPACING_STEP, DEFAULT.row_gap,
        )  # fmt: skip
        self.row_gap.slider.valueChanged.connect(
            lambda _: self._set(row_gap=self.row_gap.value())
        )
        self.add(
            Row(
                _tr("Space above the translation"),
                _tr("Between what was said and its translation."),
                self.row_gap,
            )
        )
        self.caption_gap = Slider(
            "lab.caption_gap", _tr("Space between captions"), *CAPTION_GAP_RANGE,
            SPACING_STEP, DEFAULT.caption_gap,
        )  # fmt: skip
        self.caption_gap.slider.valueChanged.connect(
            lambda _: self._set(caption_gap=self.caption_gap.value())
        )
        self.add(
            Row(
                _tr("Space between captions"),
                _tr("Between one caption and the next."),
                self.caption_gap,
            )
        )
        self.arrival_gap = Slider(
            "lab.arrival_gap",
            _tr("Gap between new captions"),
            *ARRIVAL_GAP_RANGE,
            ARRIVAL_GAP_STEP,
            DEFAULT.arrival_gap,
        )
        self.arrival_gap.slider.valueChanged.connect(
            lambda _: self._set(arrival_gap=self.arrival_gap.value())
        )
        self.add(
            Row(
                _tr("Gap between new captions"),
                _tr(
                    "Captions that arrive together come in one at a time, at least "
                    "this far apart and in order - none is dropped. 0 s: as they "
                    "come. None waits longer than the longest wait for text."
                ),
                self.arrival_gap,
            )
        )

        self.reset = QPushButton(_tr("Reset the lab"))
        self.reset.setObjectName("lab.reset")
        self.reset.setToolTip(_tr("Every setting in the Lab as Polyglotic has it."))
        self.reset.clicked.connect(view.reset_lab)
        reset = QHBoxLayout()
        reset.setContentsMargins(INSET - 1, 0, 0, 0)
        reset.addWidget(self.reset)
        reset.addStretch(1)
        self.add(reset)
        self.bind(view)
        self.refresh()

    def _set(self, **changes: object) -> None:
        self.view.set_lab(replace(self.view.value.lab, **changes))  # type: ignore[arg-type]

    def refresh(self) -> None:
        lab: CaptionLab = self.view.value.lab
        self.new_for.show_value(
            lab.new_for,
            _tr("Only the newest") if lab.new_for <= 0 else _seconds(lab.new_for),
        )
        self.new_fade.set_value(lab.new_fade)
        self.unfinished.set_value(lab.unfinished)
        self.loading.set_value(lab.loading)
        thickness = (
            LINK_PX[self.view.value.link_line] if lab.link_px is None else lab.link_px
        )
        self.link_px.show_value(thickness, _pixels(thickness))
        self.row_gap.show_value(lab.row_gap, _pixels(lab.row_gap))
        self.caption_gap.show_value(lab.caption_gap, _pixels(lab.caption_gap))
        self.new_fade.setEnabled(lab.new_for > 0)
        self.older.show_value(
            lab.older, _tr("No dimming") if lab.older >= 1.0 else _percent(lab.older)
        )
        self.arrival_gap.show_value(
            lab.arrival_gap,
            _tr("As they come") if lab.arrival_gap <= 0 else _seconds(lab.arrival_gap),
        )
