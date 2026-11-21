"""The demo video's shots, drawn with Pillow from the pipeline's real output (``demo/evidence.py``).

Written for a client, not a developer (#45): the problem first, the receipt
beside its values (Mayer's spatial contiguity), the part of the receipt each
value came from lit up (signaling), plain words only, one idea per shot, and a
caption burned in for a video that plays muted. Every shot is a list of still
frames; ``demo/render.py`` turns them into the video.
"""

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from core.result import ExtractedField
from demo.evidence import Box, Evidence, GateFacts

WIDTH = 1920
HEIGHT = 1080
BAND_TOP = 900  # the caption band, below everything else

# Catppuccin Mocha, the palette the earlier terminal video used.
BACKGROUND = (30, 30, 46)  # base
BAND = (17, 17, 27)  # crust
CARD = (49, 50, 68)  # surface0
TEXT = (205, 214, 244)  # text
MUTED = (166, 173, 200)  # subtext0
HIGHLIGHT = (249, 226, 175)  # yellow: where a value was read
CHECK = (250, 179, 135)  # peach: a value a person checks
BLOCKED = (243, 139, 168)  # red

# Every text colour on the background it is drawn on (tests/test_demo.py
# checks each against WCAG's 4.5:1).
TEXT_ON = (
    (TEXT, BACKGROUND),
    (MUTED, BACKGROUND),
    (HIGHLIGHT, BACKGROUND),
    (BLOCKED, BACKGROUND),
    (TEXT, CARD),
    (MUTED, CARD),
    (CHECK, CARD),
    (TEXT, BAND),
    (BACKGROUND, CHECK),
)

# Netflix's timed text style guide: at most 42 characters per line, 2 lines.
CAPTION_LINE = 42

_LABELS = {
    "company": "Company",
    "address": "Address",
    "date": "Date",
    "total": "Total",
    "currency": "Currency",
}

# Layout: the receipt on the left, the fields on the right.
_RECEIPT_TOP = 40
_RECEIPT_HEIGHT = 820
_RECEIPT_LEFT = 120
_FORM_LEFT = 1010
_FORM_RIGHT = 1840
_ROW_TOP = 130
_ROW_HEIGHT = 150


@dataclass(frozen=True, slots=True)
class Frame:
    image: Image.Image
    seconds: float
    texts: tuple[str, ...]  # every text drawn, so tests can read the screen
    receipt: Path | None = None  # the receipt shown, if any


@dataclass(frozen=True, slots=True)
class Shot:
    caption: str
    frames: tuple[Frame, ...]

    @property
    def seconds(self) -> float:
        return sum(frame.seconds for frame in self.frames)


def caption_lines(caption: str) -> list[str]:
    """The caption in one line, or two of balanced length, ending a sentence where it can.

    A greedy wrap leaves a lone word on the second line ("sample."); a line
    ending at a sentence or a clause reads as one thought.
    """
    if len(caption) <= CAPTION_LINE:
        return [caption]
    splits = [
        (caption[:index], caption[index + 1 :])
        for index, character in enumerate(caption)
        if character == " "
    ]
    fitting = [split for split in splits if max(map(len, split)) <= CAPTION_LINE]
    if not fitting:  # more than two lines: the caption is too long (tests/test_demo.py)
        return textwrap.wrap(caption, CAPTION_LINE)

    def unbalance(split: tuple[str, str]) -> int:
        first, second = split
        at_a_pause = first[-1] in ".?!,;:"
        return abs(len(first) - len(second)) - (_PAUSE_BONUS if at_a_pause else 0)

    return list(min(fitting, key=unbalance))


# How many characters of imbalance a break at a sentence or clause is worth.
_PAUSE_BONUS = 16


def contrast(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    """WCAG 2.2's contrast ratio, from 1 to 21."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(colour: tuple[int, int, int]) -> float:
    # WCAG 2.2, "relative luminance" (Understanding SC 1.4.3).
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


@cache
def _font(size: int) -> ImageFont.FreeTypeFont:
    # Pillow's bundled font: the same on Windows and in the render's container.
    font = ImageFont.load_default(size=size)
    if not isinstance(font, ImageFont.FreeTypeFont):  # a Pillow built without FreeType
        raise TypeError("Pillow has no FreeType: the demo cannot draw sized text")
    return font


@dataclass(slots=True)
class _Canvas:
    caption: str
    image: Image.Image = field(init=False)
    draw: ImageDraw.ImageDraw = field(init=False)
    texts: list[str] = field(default_factory=list[str])
    receipt: Path | None = None

    def __post_init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)

    def text(
        self,
        xy: tuple[float, float],
        text: str,
        *,
        size: int,
        fill: tuple[int, int, int],
        bold: bool = False,
        anchor: str = "la",
    ) -> None:
        self.draw.text(
            xy,
            text,
            font=_font(size),
            fill=fill,
            anchor=anchor,
            stroke_width=1 if bold else 0,
            stroke_fill=fill,
        )
        self.texts.append(text)

    def frame(self, seconds: float) -> Frame:
        self.draw.rectangle((0, BAND_TOP, WIDTH, HEIGHT), fill=BAND)
        lines = caption_lines(self.caption)
        middle = BAND_TOP + (HEIGHT - BAND_TOP) / 2
        for index, line in enumerate(lines):
            y = middle + (index - (len(lines) - 1) / 2) * 60
            self.text((WIDTH / 2, y), line, size=46, fill=TEXT, anchor="mm")
        return Frame(self.image, seconds, tuple(self.texts), self.receipt)


def _paste_receipt(canvas: _Canvas, path: Path) -> float:
    """Draw the receipt on the left; the scale from its pixels to the screen."""
    with Image.open(path) as receipt:
        shown = ImageOps.contain(
            receipt.convert("RGB"), (WIDTH, _RECEIPT_HEIGHT), Image.Resampling.LANCZOS
        )
        scale = shown.height / receipt.height
    canvas.image.paste(shown, (_RECEIPT_LEFT, _RECEIPT_TOP))
    canvas.receipt = path
    return scale


def _on_screen(box: Box, scale: float) -> Box:
    pad = 8
    left, top, right, bottom = box
    return (
        round(_RECEIPT_LEFT + left * scale) - pad,
        round(_RECEIPT_TOP + top * scale) - pad,
        round(_RECEIPT_LEFT + right * scale) + pad,
        round(_RECEIPT_TOP + bottom * scale) + pad,
    )


def _one_line(text: str) -> str:
    return text.replace("\n", ", ")


def _row(
    canvas: _Canvas,
    index: int,
    name: str,
    value: ExtractedField[str] | None,
    *,
    active: bool,
    to_check: bool,
) -> None:
    """One field: its label, then its value and where it came from, or a blank to fill."""
    top = _ROW_TOP + index * _ROW_HEIGHT
    left = _FORM_LEFT + 30
    if active:
        canvas.draw.rounded_rectangle(
            (_FORM_LEFT, top, _FORM_RIGHT, top + _ROW_HEIGHT - 14), radius=14, fill=CARD
        )
        canvas.draw.rectangle(
            (_FORM_LEFT, top, _FORM_LEFT + 8, top + _ROW_HEIGHT - 14),
            fill=CHECK if to_check else HIGHLIGHT,
        )
    canvas.text((left, top + 14), _LABELS[name], size=28, fill=MUTED)
    if value is None:  # not filled in yet: a blank line to type on
        canvas.draw.line((left, top + 100, _FORM_RIGHT - 40, top + 100), fill=MUTED, width=2)
        return
    if value.value is None:
        canvas.text((left, top + 48), "Not on the receipt", size=44, fill=TEXT, bold=True)
        canvas.text((left, top + 104), value.reason or "", size=26, fill=MUTED)
        return
    canvas.text(
        (left, top + 48),
        _one_line(value.value),
        size=44,
        fill=CHECK if to_check else TEXT,
        bold=True,
    )
    if value.citation is None:  # a value always has one (ExtractedField)
        return
    quote = _one_line(value.citation.quote)
    if to_check:
        # The quote too: it shows the printed form ("10.00") of a value kept
        # exact ("10", D15), and that the value was read from the faded print.
        canvas.text((left, top + 104), f"Read from the faded print: “{quote}”", size=26, fill=MUTED)
        badge = (_FORM_RIGHT - 300, top + 50, _FORM_RIGHT - 30, top + 100)
        canvas.draw.rounded_rectangle(badge, radius=25, fill=CHECK)
        canvas.text(
            ((badge[0] + badge[2]) / 2, (badge[1] + badge[3]) / 2),
            "A person checks",
            size=28,
            fill=BACKGROUND,
            bold=True,
            anchor="mm",
        )
    else:
        canvas.text((left, top + 104), f"Read from: “{quote}”", size=26, fill=MUTED)


def _form_frame(
    caption: str,
    evidence: Evidence,
    *,
    filled: Sequence[str],
    active: str | None,
    seconds: float,
) -> Frame:
    canvas = _Canvas(caption)
    scale = _paste_receipt(canvas, evidence.image)
    canvas.text((_FORM_LEFT, 50), "Receipt data", size=40, fill=TEXT, bold=True)
    fields = evidence.result.fields
    for index, name in enumerate(_LABELS):
        to_check = name in evidence.result.review
        canvas_value = fields[name] if name in filled else None
        _row(canvas, index, name, canvas_value, active=name == active, to_check=to_check)
    if active is not None:
        row_middle = _ROW_TOP + list(_LABELS).index(active) * _ROW_HEIGHT + (_ROW_HEIGHT - 14) / 2
        for box in evidence.boxes.get(active, []):
            screen = _on_screen(box, scale)
            canvas.draw.rounded_rectangle(screen, radius=8, outline=HIGHLIGHT, width=5)
            # A line from the place on the receipt to the field it filled.
            start = (screen[2], (screen[1] + screen[3]) / 2)
            canvas.draw.line((start, (_FORM_LEFT - 4, row_middle)), fill=HIGHLIGHT, width=3)
    return canvas.frame(seconds)


def _gate_frame(caption: str, gate: GateFacts, *, stamped: bool, seconds: float) -> Frame:
    canvas = _Canvas(caption)
    canvas.text(
        (WIDTH / 2, 110),
        "An update that looked harmless",
        size=56,
        fill=TEXT,
        bold=True,
        anchor="mm",
    )
    canvas.text(
        (WIDTH / 2, 185),
        f"Tested on {gate.documents} real receipts before it can ship",
        size=34,
        fill=MUTED,
        anchor="mm",
    )
    columns = ((1010, "Today", gate.current), (1500, "With the update", gate.update))
    for x, title, _ in columns:
        canvas.text((x, 300), title, size=36, fill=MUTED, anchor="mm")
    rows = ("Values read correctly", "Wrong values passed on unchecked")
    for index, label in enumerate(rows):
        y = 430 + index * 180
        canvas.draw.rounded_rectangle((180, y - 70, 1740, y + 70), radius=18, fill=CARD)
        canvas.text((230, y), label, size=40, fill=TEXT, anchor="lm")
        for x, _, score in columns:
            shown = (
                f"{score.correct} of {score.values}" if index == 0 else str(score.wrong_unchecked)
            )
            canvas.text((x, y), shown, size=56, fill=TEXT, bold=True, anchor="mm")
    if stamped:
        # Below the table, under the update's column: the numbers stay readable.
        _stamp(canvas, "NOT SHIPPED", center=(1500, 775))
    return canvas.frame(seconds)


def _stamp(canvas: _Canvas, text: str, *, center: tuple[int, int]) -> None:
    """A rubber stamp, tilted, over the update's column."""
    font = _font(72)
    left, top, right, bottom = (round(edge) for edge in font.getbbox(text, stroke_width=2))
    pad = 30
    stamp = Image.new("RGBA", (right - left + 2 * pad, bottom - top + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)
    draw.rounded_rectangle(
        (3, 3, stamp.width - 4, stamp.height - 4), radius=16, outline=BLOCKED, width=8
    )
    draw.text(
        (pad - left, pad - top), text, font=font, fill=BLOCKED, stroke_width=2, stroke_fill=BLOCKED
    )
    tilted = stamp.rotate(8, resample=Image.Resampling.BICUBIC, expand=True)
    canvas.image.paste(
        tilted,
        (center[0] - tilted.width // 2, center[1] - tilted.height // 2),
        tilted,  # its own alpha as the mask: only the stamp's ink is drawn
    )
    canvas.texts.append(text)


def _closing_frame(caption: str, seconds: float) -> Frame:
    canvas = _Canvas(caption)
    canvas.text(
        (WIDTH / 2, 400),
        "Every value traceable to the page.",
        size=72,
        fill=TEXT,
        bold=True,
        anchor="mm",
    )
    canvas.text(
        (WIDTH / 2, 510),
        "And when it can't be, a person checks it.",
        size=44,
        fill=MUTED,
        anchor="mm",
    )
    return canvas.frame(seconds)


def storyboard(receipt: Evidence, review: Evidence, gate: GateFacts) -> list[Shot]:
    """The six shots, in order (the script approved in #45)."""
    names = list(_LABELS)
    found = [name for name in names if receipt.result.fields[name].value is not None]

    problem = "Still typing receipts in by hand? Slow, and typos reach the books."
    values = "Each value comes with the exact words it was read from."
    empty = "No currency on the receipt, so the field stays empty, with the reason."
    person = "Too faint to confirm? A person checks it before it's used."
    tested = (
        f"Every update is re-tested on {gate.documents} real receipts. Worse results never ship."
    )
    contact = "Have documents like these? Send me a sample."

    return [
        Shot(problem, (_form_frame(problem, receipt, filled=[], active=None, seconds=6),)),
        Shot(
            values,
            tuple(
                _form_frame(
                    values, receipt, filled=found[: index + 1], active=name, seconds=10 / len(found)
                )
                for index, name in enumerate(found)
            ),
        ),
        Shot(empty, (_form_frame(empty, receipt, filled=names, active="currency", seconds=6),)),
        Shot(person, (_form_frame(person, review, filled=names, active="total", seconds=10),)),
        Shot(
            tested,
            (
                _gate_frame(tested, gate, stamped=False, seconds=4),
                _gate_frame(tested, gate, stamped=True, seconds=6),
            ),
        ),
        Shot(contact, (_closing_frame(contact, 6),)),
    ]
