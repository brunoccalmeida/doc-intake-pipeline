"""An image of the spreadsheet a scheduled check leaves, for the README and the portfolio (#60).

    uv run poe demo-sheet

Runs the inbox demo (``scripts/inbox_demo.py``: the two demo receipts,
replayed, no key, no cost) and draws its ``results.csv`` into
``demo/spreadsheet.png``. A still image, not a video: research for #60 found no
evidence that a video of the flow would win clients, and a folder, a schedule
and a spreadsheet gain nothing from motion.

It shows the rows of the one receipt with a value to check, not the whole
file: a crop to what proves the point keeps the text readable in Upwork's small
preview (research for #60: NN/g on shrunk images, screenshot guides). The grid
copies those rows word for word, column names included, because that is what
the client filters. The CSV has no colours, so the row a person checks is
framed around its cells, with a tab in the margin, never filled with a colour
the client would not see. The words around the grid are for the buyer, in the
video's palette and font.
"""

import csv
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from demo.storyboard import BACKGROUND, BORDER, CARD, CHECK, MUTED, TEXT, Colour, font
from doc_intake import batch
from scripts import inbox_demo

IMAGE = Path("demo/spreadsheet.png")

# Upwork shows portfolio images at 4:3, at least 1000 px wide (#60).
WIDTH = 1600
HEIGHT = 1200

# The columns a buyer reads; the others (file, named above the grid, document
# status, page, source) stay in the file. "note" is wrapped inside its cell.
SHOWN = ("field", "field_status", "value", "quote", "note")
_WRAPPED = "note"
_COLUMNS_IN_FILE = len(batch.COLUMNS)

HEADER: Colour = (241, 245, 249)  # slate-100

_MARGIN = 60
_GRID_LEFT = 200  # left of it, the tab naming the row a person checks
_GRID_RIGHT = WIDTH - _MARGIN
_GRID_TOP = 350
CELL_SIZE = 28
_CELL_PAD = 16
_LINE = 38
_ROW_PAD = 22
_MIN_WRAPPED = 260
_FRAME = 4  # the frame around the row a person checks

type Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Sheet:
    image: Image.Image
    file: str  # the receipt whose rows are shown
    cells: tuple[tuple[str, ...], ...]  # the grid's data rows, as in the file
    marked: tuple[int, ...]  # the rows a person checks, by index
    texts: tuple[str, ...]  # every word drawn around the grid, for the buyer
    # Where each part sits: none may come near another or leave the image.
    blocks: tuple[tuple[str, Box], ...]
    # Each text in the box it is written in: (name, its box, the box around it).
    nested: tuple[tuple[str, Box, Box], ...]
    # Every (text colour, colour under it) pair drawn, for the contrast test.
    colours: tuple[tuple[Colour, Colour], ...]


def results_csv(root: Path) -> Path:
    """Run the inbox demo into ``root`` and return the spreadsheet it left."""
    if inbox_demo.main(root) != 0:
        raise RuntimeError(f"the inbox demo failed in {root}: see its summary line")
    found = sorted(root.glob("runs/*/results.csv"))
    if len(found) != 1:
        raise RuntimeError(f"expected one results.csv under {root / 'runs'}, found {len(found)}")
    return found[0]


def read_rows(path: Path) -> list[dict[str, str]]:
    # utf-8-sig: the file starts with a BOM, so Excel reads it as UTF-8.
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _receipt_to_check(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """The rows of the first receipt with a value a person checks."""
    for row in rows:
        if row["field_status"] == "needs_review":
            return [other for other in rows if other["file"] == row["file"]]
    raise ValueError("the spreadsheet has no value to check: the image would show nothing")


def _wrap(text: str, width: float) -> list[str]:
    """Break each line of ``text`` at spaces to fit ``width``, as a cell's wrap text does."""
    cell = font(CELL_SIZE)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and cell.getlength(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    if any(cell.getlength(line) > width for line in lines):
        raise ValueError(f"a word of {text!r} does not fit its cell")
    return lines


def _widths(rows: Sequence[dict[str, str]]) -> dict[str, float]:
    """Each column as wide as its widest line; the wrapped one takes what is left."""
    cell = font(CELL_SIZE)
    widths = {
        column: max(
            cell.getlength(column) + 2,  # +2: the bold stroke
            *(cell.getlength(line) for row in rows for line in row[column].split("\n")),
        )
        + 2 * _CELL_PAD
        for column in SHOWN
        if column != _WRAPPED
    }
    left = _GRID_RIGHT - _GRID_LEFT - sum(widths.values())
    if left < _MIN_WRAPPED:
        raise ValueError(
            f"the grid does not fit the image: {_WRAPPED!r} would be {left:.0f} px wide"
        )
    widths[_WRAPPED] = left
    return {column: widths[column] for column in SHOWN}


@dataclass(slots=True)
class _Painter:
    """Draws every text, noting its words and the colours it sets on what."""

    draw: ImageDraw.ImageDraw
    texts: list[str] = field(default_factory=list[str])
    colours: set[tuple[Colour, Colour]] = field(default_factory=set[tuple[Colour, Colour]])

    def say(
        self,
        xy: tuple[float, float],
        text: str,
        *,
        size: int,
        fill: Colour,
        on: Colour,
        bold: bool = False,
        anchor: str = "la",
    ) -> Box:
        """Draw words for the buyer, keep them for the tests to read, and return where they sit."""
        self.cell(xy, text, size=size, fill=fill, on=on, bold=bold, anchor=anchor)
        self.texts.append(text)
        return self.draw.textbbox(
            xy, text, font=font(size), anchor=anchor, stroke_width=1 if bold else 0
        )

    def cell(
        self,
        xy: tuple[float, float],
        text: str,
        *,
        on: Colour,
        size: int = CELL_SIZE,
        fill: Colour = TEXT,
        bold: bool = False,
        anchor: str = "la",
    ) -> None:
        self.colours.add((fill, on))
        self.draw.text(
            xy,
            text,
            font=font(size),
            fill=fill,
            anchor=anchor,
            stroke_width=1 if bold else 0,
            stroke_fill=fill,
        )


def draw(all_rows: Sequence[dict[str, str]]) -> Sheet:
    receipt = _receipt_to_check(all_rows)
    # An empty field with nothing to check proves nothing here: cropped like the
    # unshown columns, and counted in the footer (#66).
    rows = [row for row in receipt if row["value"] or row["field_status"] == "needs_review"]
    hidden = len(receipt) - len(rows)
    widths = _widths(rows)
    wrapped = [
        {
            column: _wrap(row[column], widths[column] - 2 * _CELL_PAD)
            if column == _WRAPPED
            else row[column].split("\n")
            for column in SHOWN
        }
        for row in rows
    ]
    marked = tuple(index for index, row in enumerate(rows) if row["field_status"] == "needs_review")
    file = rows[0]["file"]

    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    canvas = ImageDraw.Draw(image)
    paint = _Painter(canvas)
    blocks: list[tuple[str, Box]] = []
    nested: list[tuple[str, Box, Box]] = []

    # The claim, short enough to read in a thumbnail; then how it happens.
    headline = "Receipts in. A spreadsheet out."
    blocks.append(
        (
            "headline",
            paint.say(
                (WIDTH / 2, 120),
                headline,
                size=64,
                fill=TEXT,
                on=BACKGROUND,
                bold=True,
                anchor="mm",
            ),
        )
    )
    subline = (
        "Drop receipts in a folder. Each scheduled check adds one row per value to a spreadsheet."
    )
    blocks.append(
        (
            "subline",
            paint.say((WIDTH / 2, 200), subline, size=30, fill=MUTED, on=BACKGROUND, anchor="mm"),
        )
    )
    label = f"The rows of one receipt, {file}:"
    blocks.append(
        (
            "label",
            paint.say(
                (_GRID_LEFT, _GRID_TOP - 30), label, size=28, fill=MUTED, on=BACKGROUND, anchor="ls"
            ),
        )
    )

    # The grid: a header with the file's own column names, then the receipt's rows.
    heights = [_ROW_PAD + _LINE * max(len(lines) for lines in row.values()) for row in wrapped]
    header = _ROW_PAD + _LINE
    bottom = _GRID_TOP + header + sum(heights)
    canvas.rectangle(
        (_GRID_LEFT, _GRID_TOP, _GRID_RIGHT, bottom), fill=CARD, outline=BORDER, width=2
    )
    canvas.rectangle(
        (_GRID_LEFT, _GRID_TOP, _GRID_RIGHT, _GRID_TOP + header),
        fill=HEADER,
        outline=BORDER,
        width=2,
    )
    x = float(_GRID_LEFT)
    for column in SHOWN:
        paint.cell(
            (x + _CELL_PAD, _GRID_TOP + header / 2), column, on=HEADER, bold=True, anchor="lm"
        )
        x += widths[column]
        if column != SHOWN[-1]:
            canvas.line((x, _GRID_TOP, x, bottom), fill=BORDER, width=2)
    top = float(_GRID_TOP + header)
    to_frame: list[tuple[float, float]] = []
    for index, (row, height) in enumerate(zip(wrapped, heights, strict=True)):
        x = float(_GRID_LEFT)
        for column in SHOWN:
            for number, line in enumerate(row[column]):
                paint.cell((x + _CELL_PAD, top + _ROW_PAD / 2 + 4 + number * _LINE), line, on=CARD)
            x += widths[column]
        if index in marked:
            to_frame.append((top, top + height))
        top += height
        canvas.line((_GRID_LEFT, top, _GRID_RIGHT, top), fill=BORDER, width=2)
    grid_left = float(_GRID_LEFT)
    for row_top, row_bottom in to_frame:  # drawn last, over the row lines
        tab, word = _mark(canvas, paint, row_top, row_bottom)
        nested.append(("mark", word, tab))
        grid_left = min(grid_left, tab[0])
    blocks.append(("grid", (grid_left, _GRID_TOP, _GRID_RIGHT + _FRAME, bottom + _FRAME)))

    # What the frame means, in the buyer's words; the column is named as it reads.
    count = len(marked)
    which = "the flagged value goes" if count == 1 else f"the {count} flagged values go"
    caption = f"Only {which} to a person, with the words it was read from and why."
    how = "Filter field_status for needs_review to list them across every receipt."
    first = paint.say(
        (WIDTH / 2, bottom + 80), caption, size=32, fill=TEXT, on=BACKGROUND, bold=True, anchor="mm"
    )
    second = paint.say(
        (WIDTH / 2, bottom + 132), how, size=28, fill=MUTED, on=BACKGROUND, anchor="mm"
    )
    blocks.append(
        ("caption", (min(first[0], second[0]), first[1], max(first[2], second[2]), second[3]))
    )

    others = len({row["file"] for row in all_rows}) - 1
    footer = (
        f"Fictional sample receipts. {len(SHOWN)} of the spreadsheet's {_COLUMNS_IN_FILE} "
        f"columns shown; {hidden} empty fields and the rows of {others} other "
        f"{'receipt' if others == 1 else 'receipts'} in the same check are not."
    )
    blocks.append(
        (
            "footer",
            paint.say(
                (WIDTH / 2, HEIGHT - 36), footer, size=22, fill=MUTED, on=BACKGROUND, anchor="mm"
            ),
        )
    )
    cells = tuple(tuple(row[column] for column in SHOWN) for row in rows)
    return Sheet(
        image,
        file,
        cells,
        marked,
        tuple(paint.texts),
        tuple(blocks),
        tuple(nested),
        tuple(sorted(paint.colours)),
    )


def _mark(
    canvas: ImageDraw.ImageDraw, paint: _Painter, top: float, bottom: float
) -> tuple[Box, Box]:
    """Frame the row a person checks, with a tab in the margin naming it.

    Returns the tab and the word on it.
    """
    canvas.rectangle(
        (_GRID_LEFT - _FRAME, top - _FRAME / 2, _GRID_RIGHT + _FRAME, bottom + _FRAME / 2),
        outline=CHECK,
        width=_FRAME,
    )
    tab = (float(_MARGIN), top - _FRAME / 2, float(_GRID_LEFT), bottom + _FRAME / 2)
    canvas.rounded_rectangle(tab, radius=10, fill=CHECK, corners=(True, False, False, True))
    word = paint.say(
        ((tab[0] + tab[2]) / 2, (top + bottom) / 2),
        "Check",
        size=28,
        fill=CARD,
        on=CHECK,
        bold=True,
        anchor="mm",
    )
    return tab, word


def main() -> None:
    sheet = draw(read_rows(results_csv(Path(".cache/demo/sheet"))))
    sheet.image.save(IMAGE, optimize=True)
    print(f"{IMAGE}: {sheet.file}, {len(sheet.cells)} rows, {len(sheet.marked)} to check")


if __name__ == "__main__":
    main()
