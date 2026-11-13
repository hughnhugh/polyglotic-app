"""The caption layout engine: caption lines laid out for a width and text
size, and painted - shared by the caption windows and the transcripts
(decision 0031).

What keeps it fast (polyglotic-hq project 108's audit of today's overlay):
- **Only what shows:** a surface asks for the lines it draws, as
  `views.scroll` walks them; nothing is laid out ahead.
- **Cached per caption x width x text size:** a line's layout is kept while
  its rows stay the same, for its last few widths and text sizes - so a
  resize lays out the lines in view once per width, and a new caption
  lays out only itself - for as many lines as the surface can show again
  (`lines_kept`), never every line it ever showed.
- **Painted directly:** each row's `QTextLayout` is drawn by the painter,
  never turned into painter paths (`strokePath` was 75-85 % of today's
  slow actions).
- **Marks at paint time:** highlights and word links are format ranges
  drawn over a layout (`paint`'s `marks`), so a Learning change repaints
  and lays nothing out.

Sizes and fonts come from `CaptionStyle`; colours from `Ink`, at paint
time. Holds caption text in its layouts: never log them.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QTextCharFormat,
    QTextFormat,
    QTextLayout,
    QTextLine,
    QTextOption,
)

from polyglotic_desktop.core.listening.display import (
    CaptionRow,
    LinkGap,
    LinkLine,
    RowKind,
)
from polyglotic_desktop.ui_next import fonts, style
from polyglotic_desktop.ui_next.views.captions import CAPTION_WINDOW_LINES, Line

LATIN_FAMILIES = ("Segoe UI Variable Display", "Segoe UI", *fonts.also("latin"))
CJK_FAMILIES = {  # Windows' first; then another OS's own (`fonts`)
    "zh": ("Microsoft YaHei UI", "Microsoft YaHei", *fonts.also("zh")),
    "zh-hant": ("Microsoft JhengHei UI", "Microsoft JhengHei", *fonts.also("zh-hant")),
    "yue": ("Microsoft JhengHei UI", "Microsoft JhengHei", *fonts.also("yue")),
    "ja": ("Yu Gothic UI", "Meiryo UI", *fonts.also("ja")),
}
CJK_SCALE = 1.05
"""Chinese and Japanese a touch larger than Latin text at the same pixel
size: their denser strokes read as easily (today's overlay's)."""


LINK_PX = {LinkLine.THIN: 1.4, LinkLine.MEDIUM: 2.2, LinkLine.THICK: 3.4}
LINK_GAP_PX = {LinkGap.CLOSE: 0.5, LinkGap.MEDIUM: 2.0, LinkGap.FAR: 4.0}
"""A word link's underline at 21 px text: its thickness, and its gap below
the font's descent - below the descenders of g, y and 的's peers, never
through them (the user's rehearsal feedback F14, 249)."""
LINK_MARK = QTextFormat.Property.UserProperty + 1
"""A format range that is a word link: the property is its link's number
in the clause, its colour the format's underline colour; the layout draws
its underline (`_underlines`) and, with Arrows, its curve (`_arrows`)."""
ARROW_ROW_GAP, ARROW_CLAUSE_GAP = 14.0, 8.0
"""With Arrows, more room - pixels at text size 1.0 - between a clause and
its translation, for the curves to cross, and between clauses (today's
overlay had 18 and 28 in all, before 151 retired Arrows; polyglotic-hq
249 brought them back, F7)."""
ARROW_PX = 1.7
"""A curve's width at 21 px text."""


@dataclass(frozen=True, slots=True)
class CaptionStyle:
    """Sizes, in pixels at text size 1.0: the text, the gap between a
    clause's original and its translation, and between clauses."""

    text_px: float = 21.0
    row_gap: float = 2.0
    clause_gap: float = 8.0
    weight: QFont.Weight = QFont.Weight.Medium
    label_px: float = 13.0
    label_gap: float = 3.0
    family: str | None = None
    """The learner's font for the captions (the Look panel's); None: the
    app's own. Qt falls back from it per character."""
    link_px: float = LINK_PX[LinkLine.MEDIUM]
    link_gap: float = LINK_GAP_PX[LinkGap.MEDIUM]
    """A word link's underline: how thick, and how far below the font's
    descent (F14) - pixels at 21 px text, scaled with it."""
    link_room: bool = False
    """Room under every row for a word link's underline (word links shown
    underlined): the underline is below the descenders, so without it the
    next row's tops would touch it."""
    arrows: bool = False
    """Word links joined by curves too (Arrows, F7): room between a clause
    and its translation for them to cross, and between clauses."""
    caption_gap: float = 10.0
    """Between one caption and the next (the surface's; the Lab's, 284)."""
    italic_provisional: bool = True
    italic_live: bool = False
    """Text still being spoken in italic: a provisional line (today's), a
    live caption (the Lab's Text still being spoken, 284)."""


@dataclass(frozen=True)
class Ink:
    """Colours, applied at paint time: white is what was said, yellow is
    always a translation (as today's overlay); a live line, and Quick
    preview's provisional one, drawn fainter."""

    original: QColor = field(default_factory=lambda: QColor("#ffffff"))
    translation: QColor = field(default_factory=lambda: QColor("#ffd76e"))
    label: QColor = field(default_factory=lambda: QColor("#aab2c0"))
    """A label without a colour of its own (the language spoken alone)."""
    live_alpha: float = 0.85
    provisional_alpha: float = 0.6
    unfinished: QColor | None = None
    """Text still being spoken - a live or provisional line, both rows - in
    this colour instead (the Lab's, 284); None: the rows' own."""
    alpha: float = 1.0
    """Everything drawn this much fainter (Strip's previous caption)."""
    translation_alpha: float = 1.0
    """The translation rows, and the label, this much fainter again than
    `alpha` - or less faint, above 1: an older caption's yellow steps back
    less than what was said (`views.arrivals`, F21)."""


@dataclass(frozen=True, slots=True)
class LaidRow:
    """A row laid out: its layout, its top within the line, and its index
    in the line's rows (what its marks are asked for by - a Strip shows
    some of a line's rows, not from the first)."""

    row: CaptionRow
    layout: QTextLayout
    top: float
    index: int


@dataclass(frozen=True, slots=True)
class LaidLine:
    """A line laid out: its rows, its height, and the label above them
    (`label`, None for none; the rows' tops already leave room for it)."""

    rows: tuple[LaidRow, ...]
    height: float
    label: QTextLayout | None = None


Mark = tuple[int, int, QTextCharFormat]
"""Characters `[start, end)` of a row, drawn with a format (a highlight,
a word link) - at paint time, over the layout. A dotted or dashed underline
is drawn as dots or dashes below where an underline goes, so a word both
linked and in the deck shows both."""

Marks = Callable[[Line, int], Sequence[Mark]]
"""The marks for a line's row, by the row's index."""


class _Kept:
    """A line's layouts while its rows stay the same, by (width, text size)."""

    __slots__ = ("label", "live", "provisional", "rows", "sized")

    def __init__(self, line: Line) -> None:
        self.rows = line.rows
        self.provisional = line.provisional
        self.live = line.live
        self.label = line.label
        self.sized: OrderedDict[tuple[int, float], LaidLine] = OrderedDict()

    def holds(self, line: Line) -> bool:
        return (
            (self.rows is line.rows or self.rows == line.rows)
            and self.provisional == line.provisional
            and self.live == line.live
            and self.label == line.label
        )


class CaptionLayout:
    """Lines laid out and painted. One per surface; not thread-safe."""

    SIZES_KEPT = 4
    """Widths x text sizes kept per line: a resize step, and the ones it may
    go back to."""

    def __init__(
        self,
        style: CaptionStyle | None = None,
        *,
        lines_kept: int = CAPTION_WINDOW_LINES,
    ) -> None:
        """`lines_kept`: lines whose layouts are kept, least recently used
        dropped first - no more than the surface can show again: a caption
        window's lines, a few screens of a transcript (polyglotic-hq 239:
        each kept line holds its rows' `QTextLayout`s, about 15 KB of Qt's
        memory, and 2,500 kept per surface grew the app 0.5 MB a minute
        over an evening)."""
        self.style = style or CaptionStyle()
        self.lines_kept = lines_kept
        self.laid_out = 0  # rows laid out since made: what tests count
        self._kept: OrderedDict[int, _Kept] = OrderedDict()
        self._fonts: dict[tuple[tuple[str, ...], int, bool], QFont] = {}

    @property
    def held(self) -> int:
        """Lines whose layouts are kept now (at most `lines_kept`)."""
        return len(self._kept)

    def laid(self, line: Line, width: int, text_size: float) -> LaidLine:
        """`line` laid out `width` pixels wide at `text_size`: from the
        cache unless its rows changed or it wasn't laid out so before."""
        kept = self._kept.get(line.key)
        if kept is None or not kept.holds(line):
            kept = self._kept[line.key] = _Kept(line)
        self._kept.move_to_end(line.key)
        size = (width, text_size)
        found = kept.sized.get(size)
        if found is not None:
            kept.sized.move_to_end(size)
            return found
        found = kept.sized[size] = self._lay_out(line, width, text_size)
        if len(kept.sized) > self.SIZES_KEPT:
            kept.sized.popitem(last=False)
        if len(self._kept) > self.lines_kept:
            self._kept.popitem(last=False)
        return found

    def paint(
        self,
        painter: QPainter,
        line: Line,
        laid: LaidLine,
        at: QPointF,
        ink: Ink,
        marks: Marks | None = None,
    ) -> None:
        """Draws `laid` (the layout of `line`) with its top left at `at`."""
        alpha = ink.alpha * (
            ink.provisional_alpha
            if line.provisional
            else ink.live_alpha
            if line.live
            else 1.0
        )
        if laid.label is not None:
            label = QColor(line.label_color) if line.label_color else QColor(ink.label)
            label.setAlphaF(
                min(1.0, label.alphaF() * ink.alpha * ink.translation_alpha * 0.9)
            )
            painter.setPen(label)
            laid.label.draw(painter, at)
        clip = painter.clipBoundingRect() if painter.hasClipping() else None
        above: dict[int, list[QPointF]] = {}  # Arrows: the clause's upper row's ends
        for row in laid.rows:
            top_left = QPointF(at.x(), at.y() + row.top)
            if clip is not None and (
                top_left.y() + row.layout.boundingRect().height() <= clip.top()
                or top_left.y() >= clip.bottom()
            ):
                continue  # out of view, marks included: dots sit below a row's
                # box, and a row under the hover band leaked them into the gap
            original = row.row.kind is RowKind.ORIGINAL
            color = QColor(ink.original if original else ink.translation)
            if ink.unfinished is not None and (line.live or line.provisional):
                color = QColor(ink.unfinished)
            row_alpha = alpha if original else min(1.0, alpha * ink.translation_alpha)
            if row_alpha < 1.0:
                color.setAlphaF(color.alphaF() * row_alpha)
            painter.setPen(color)
            selections, dotted, links = split_marks(
                marks(line, row.index) if marks else ()
            )
            row.layout.draw(painter, top_left, selections)
            if dotted:
                _dots(painter, row.layout, top_left, dotted, alpha)
            if links:
                _underlines(painter, row.layout, top_left, links, alpha, self.style)
            if self.style.arrows:
                if row.row.starts_clause:
                    above = _ends(row.layout, top_left, links, self.style, upper=True)
                elif links and above:
                    _arrows(
                        painter, row.layout, top_left, links, above, alpha, self.style
                    )

    def _lay_out(self, line: Line, width: int, text_size: float) -> LaidLine:
        style = self.style
        rows = []
        y = 0.0
        label = None
        if line.label:
            font = self._label_font(text_size)
            label, height = _laid_text(line.label, font, width)
            y = height + style.label_gap * text_size
        for index, row in enumerate(line.rows):
            if index:
                gap = style.clause_gap if row.starts_clause else style.row_gap
                if style.arrows:  # every pair: a row doesn't jump as links come
                    gap += ARROW_CLAUSE_GAP if row.starts_clause else ARROW_ROW_GAP
                y += gap * text_size
            italic = (
                style.italic_provisional if line.provisional else style.italic_live
            ) and (line.provisional or line.live)
            font = self._font(row, text_size, italic)
            layout, height = _laid_text(row.text, font, width)
            rows.append(LaidRow(row, layout, y, index))
            y += height + (self._link_room(font) if style.link_room else 0.0)
            self.laid_out += 1
        return LaidLine(tuple(rows), y, label)

    def _link_room(self, font: QFont) -> float:
        """How far a word link's underline reaches below a row's descent."""
        scale = max(0.5, font.pixelSize() / 21.0)
        return (self.style.link_gap + self.style.link_px) * scale

    def _label_font(self, text_size: float) -> QFont:
        px = max(8, round(self.style.label_px * min(text_size, 1.6)))
        families = tuple(style.UI_FAMILIES)  # the interface's words: an app, a language
        key = (families, -px, False)
        font = self._fonts.get(key)
        if font is None:
            font = self._fonts[key] = QFont()
            font.setFamilies(list(families))
            font.setPixelSize(px)
            font.setWeight(QFont.Weight.DemiBold)
        return font

    def _font(self, row: CaptionRow, text_size: float, italic: bool) -> QFont:
        script = row.language if row.language is not None else _script(row.text)
        cjk = script in CJK_FAMILIES
        families = LATIN_FAMILIES
        if script is not None and cjk:
            families = (*CJK_FAMILIES[script], *LATIN_FAMILIES)
        if self.style.family:
            families = (self.style.family, *families)
        px = max(8, round(self.style.text_px * text_size * (CJK_SCALE if cjk else 1.0)))
        key = (families, px, italic)
        font = self._fonts.get(key)
        if font is None:
            font = self._fonts[key] = QFont()
            font.setFamilies(list(families))
            font.setPixelSize(px)
            font.setWeight(self.style.weight)
            font.setItalic(italic)
        return font


_DOTTED = QTextCharFormat.UnderlineStyle.DotLine
_DASHED = QTextCharFormat.UnderlineStyle.DashUnderline
DOT_PX, DOT_STEP_PX, DOT_DROP_PX = 1.7, 4.5, 2.0
"""A dotted mark's dots, at text size 1.0 (21 px): their size, spacing, and
how far below the underline's place they sit."""
DASH_PX, DASH_STEP_PX = 5.0, 7.5
"""A dashed mark's dashes (a word in the deck): their length and spacing,
as high as a dot; a different shape from the dots, not only a different
colour."""

Linked = tuple[int, int, QColor, int]
"""Characters `[start, end)` of a row a word link underlines, in its
colour, and the link's number in the clause."""

Dotted = tuple[int, int, QColor, bool]
"""Characters `[start, end)` marked below the underline's place, in a
colour; dashes rather than dots if the last is True."""


def split_marks(
    marks: Sequence[Mark],
) -> tuple[list[QTextLayout.FormatRange], list[Dotted], list[Linked]]:
    """A row's marks as the format ranges Qt draws with its text, and apart:
    the dotted and dashed ones - drawn as dots or dashes below where an
    underline goes, so an underline on the same word doesn't replace them -
    and the word links, underlined below the descenders (`_underlines`)."""
    selections = []
    dotted = []
    links = []
    for start, end, format_ in marks:
        if format_.hasProperty(LINK_MARK):
            link = int(format_.property(LINK_MARK))
            links.append((start, end, format_.underlineColor(), link))
            continue
        style = format_.underlineStyle()
        if style is _DOTTED or style is _DASHED:
            dotted.append((start, end, format_.underlineColor(), style is _DASHED))
            continue
        selection = QTextLayout.FormatRange()
        selection.start, selection.length = start, end - start
        selection.format = format_
        selections.append(selection)
    return selections, dotted, links


def cursor_x(line: QTextLine, index: int) -> float:
    """Where character `index` starts on a laid-out line."""
    found: object = line.cursorToX(index)  # (x, index) in PySide6
    return float(found[0] if isinstance(found, tuple) else found)  # type: ignore[arg-type]


def char_under(
    rows: Iterable[tuple[LaidRow, QPointF]], pos: QPointF
) -> tuple[LaidRow, QPointF, int] | None:
    """The character under `pos` among `rows` - each a laid-out row and its
    top left, where it's drawn: that row, its top left and the character's
    index in its text; None if `pos` is on no text. Caption windows and
    transcripts find the word under the mouse with it."""
    for row, origin in rows:
        layout = row.layout
        for i in range(layout.lineCount()):
            text_line = layout.lineAt(i)
            if text_line.naturalTextRect().translated(origin).contains(pos):
                index = text_line.xToCursor(
                    pos.x() - origin.x(), QTextLine.CursorPosition.CursorOnCharacter
                )
                return row, origin, index
    return None


def span_rects(layout: QTextLayout, start: int, end: int) -> list[QRectF]:
    """Where characters `[start, end)` of `layout` are, one rectangle per
    line they're on - from the layout's own top left."""
    rects = []
    for i in range(layout.lineCount()):
        text_line = layout.lineAt(i)
        a = max(start, text_line.textStart())
        b = min(end, text_line.textStart() + text_line.textLength())
        if a < b:
            x1, x2 = cursor_x(text_line, a), cursor_x(text_line, b)
            rects.append(QRectF(x1, text_line.y(), x2 - x1, text_line.height()))
    return rects


def _dots(
    painter: QPainter,
    layout: QTextLayout,
    at: QPointF,
    spans: list[Dotted],
    alpha: float,
) -> None:
    """Dots - or dashes - under characters `[start, end)` of `layout`
    (drawn at `at`), below where an underline goes."""
    font = layout.font()
    scale = max(0.5, font.pixelSize() / 21.0)
    metrics = QFontMetricsF(font)
    drop = metrics.underlinePos() + metrics.lineWidth() + DOT_DROP_PX * scale
    size = DOT_PX * scale
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for start, end, color, dashed in spans:
        length = DASH_PX * scale if dashed else size
        step = (DASH_STEP_PX if dashed else DOT_STEP_PX) * scale
        dot = QColor(color)
        dot.setAlphaF(dot.alphaF() * alpha)
        painter.setBrush(dot)
        for i in range(layout.lineCount()):
            text_line = layout.lineAt(i)
            a = max(start, text_line.textStart())
            b = min(end, text_line.textStart() + text_line.textLength())
            if a >= b:
                continue
            x = at.x() + cursor_x(text_line, a) + 1
            right = at.x() + cursor_x(text_line, b)
            y = at.y() + text_line.y() + text_line.ascent() + drop
            while x + length <= right:
                if dashed:
                    painter.drawRoundedRect(
                        QRectF(x, y, length, size), size / 2, size / 2
                    )
                else:
                    painter.drawEllipse(QRectF(x, y, size, size))
                x += step
    painter.restore()


def _underlines(
    painter: QPainter,
    layout: QTextLayout,
    at: QPointF,
    links: list[Linked],
    alpha: float,
    style: CaptionStyle,
) -> None:
    """Word links' underlines under characters `[start, end)` of `layout`
    (drawn at `at`): below the font's descent - under the descenders, never
    through them - `style.link_gap` further, `style.link_px` thick, both
    scaled with the text (F14)."""
    scale = max(0.5, layout.font().pixelSize() / 21.0)
    thick = style.link_px * scale
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for start, end, color, _ in links:
        bar = QColor(color)
        bar.setAlphaF(bar.alphaF() * alpha)
        painter.setBrush(bar)
        for i in range(layout.lineCount()):
            text_line = layout.lineAt(i)
            a = max(start, text_line.textStart())
            b = min(end, text_line.textStart() + text_line.textLength())
            if a >= b:
                continue
            x1 = at.x() + cursor_x(text_line, a)
            x2 = at.x() + cursor_x(text_line, b)
            bottom = text_line.y() + text_line.ascent() + text_line.descent()
            y = at.y() + bottom + style.link_gap * scale
            painter.drawRoundedRect(QRectF(x1, y, x2 - x1, thick), thick / 2, thick / 2)
    painter.restore()


def _ends(
    layout: QTextLayout,
    at: QPointF,
    links: list[Linked],
    style: CaptionStyle,
    upper: bool,
) -> dict[int, list[QPointF]]:
    """Where Arrows' curves end on a row (drawn at `at`), by link: under the
    middle of each linked word on its last line (`upper`, just below its
    underline) - or over it on its first line. Only the lines facing each
    other: a curve from an upper line would cut through the text."""
    found: dict[int, list[QPointF]] = {}
    if not layout.lineCount():
        return found
    scale = max(0.5, layout.font().pixelSize() / 21.0)
    text_line = layout.lineAt(layout.lineCount() - 1 if upper else 0)
    for start, end, _, link in links:
        a = max(start, text_line.textStart())
        b = min(end, text_line.textStart() + text_line.textLength())
        if a >= b:
            continue
        middle = at.x() + (cursor_x(text_line, a) + cursor_x(text_line, b)) / 2
        if upper:
            bottom = text_line.y() + text_line.ascent() + text_line.descent()
            y = bottom + (style.link_gap + style.link_px) * scale  # from the bar
        else:
            y = text_line.y() + 1.0 * scale
        found.setdefault(link, []).append(QPointF(middle, at.y() + y))
    return found


def _arrows(
    painter: QPainter,
    layout: QTextLayout,
    at: QPointF,
    links: list[Linked],
    above: dict[int, list[QPointF]],
    alpha: float,
    style: CaptionStyle,
) -> None:
    """Arrows (F7): from each linked word of a clause's upper row (`above`)
    a curve down to its counterpart on this, its translation row, in the
    link's colour (today's overlay's, before 151)."""
    scale = max(0.5, layout.font().pixelSize() / 21.0)
    colors = {link: color for _, _, color, link in links}
    pen = QPen()
    pen.setWidthF(ARROW_PX * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for link, ends in _ends(layout, at, links, style, upper=False).items():
        color = QColor(colors[link])
        color.setAlphaF(color.alphaF() * 0.9 * alpha)
        pen.setColor(color)
        painter.setPen(pen)
        for end in ends:
            for start in above.get(link, ()):
                bend = (end.y() - start.y()) * 0.6
                curve = QPainterPath(start)
                curve.cubicTo(
                    QPointF(start.x(), start.y() + bend),
                    QPointF(end.x(), end.y() - bend),
                    end,
                )
                painter.drawPath(curve)
    painter.restore()


def _laid_text(text: str, font: QFont, width: int) -> tuple[QTextLayout, float]:
    """`text` laid out in `font`, wrapped at `width`; and its height."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.setCacheEnabled(True)
    layout.beginLayout()
    height = 0.0
    while True:
        text_line = layout.createLine()
        if not text_line.isValid():
            break
        text_line.setLineWidth(max(10, width))
        text_line.setPosition(QPointF(0, height))
        height += text_line.height()
    layout.endLayout()
    return layout, height


def _cjk_share(text: str) -> float:
    """How much of `text` is Chinese or Japanese characters."""
    if not text:
        return 0.0
    cjk = sum(1 for c in text if "⺀" <= c <= "鿿" or "豈" <= c <= "﫿")
    return cjk / len(text)


def _script(text: str) -> str | None:
    """The fonts for text in a language not known, by its script: "ja" with
    kana, "zh" for other Chinese characters, None for neither. Han
    characters are one script in Chinese and Japanese; only the kana say
    it's Japanese (polyglotic-hq 215: such a line was in YaHei, a Chinese
    face, with China's glyph shapes)."""
    if _cjk_share(text) <= 0.3:
        return None
    return "ja" if any(_is_kana(c) for c in text) else "zh"


def _is_kana(c: str) -> bool:
    """Hiragana, katakana (and its extensions), half-width katakana."""
    return "぀" <= c <= "ヿ" or "ㇰ" <= c <= "ㇿ" or "ｦ" <= c <= "ﾟ"
