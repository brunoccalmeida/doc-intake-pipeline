"""The spreadsheet image shows what a scheduled check really leaves (#60).

Drawn from the ``results.csv`` of ``uv run poe inbox-demo`` (replayed, no
cost), so it cannot show a value the pipeline did not produce. It shows the
rows of the one receipt with a value to check, large enough to read in
Upwork's small preview. The grid copies the file word for word, column names
included, because that is what the client filters; the words around it are
written for the buyer, not for a developer.
"""

import re
from pathlib import Path

import pytest
from PIL import Image

from demo import spreadsheet, storyboard


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # One replayed run for the module: the inbox demo states its own provider
    # and model and only replays, so no setting or key of the shell reaches it.
    return spreadsheet.results_csv(tmp_path_factory.mktemp("inbox"))


@pytest.fixture(scope="module")
def sheet(results: Path) -> spreadsheet.Sheet:
    return spreadsheet.draw(spreadsheet.read_rows(results))


def test_the_grid_holds_the_rows_of_the_receipt_to_check_word_for_word(
    results: Path, sheet: spreadsheet.Sheet
) -> None:
    rows = spreadsheet.read_rows(results)
    review = [row for row in rows if row["file"] == "receipt-review.png"]

    assert len(rows) == 10  # two receipts, five fields each
    assert sheet.file == "receipt-review.png"
    assert sheet.cells == tuple(
        tuple(row[column] for column in spreadsheet.SHOWN) for row in review
    )


def test_only_the_value_a_person_checks_is_marked(sheet: spreadsheet.Sheet) -> None:
    field = spreadsheet.SHOWN.index("field")

    assert [sheet.cells[index][field] for index in sheet.marked] == ["total"]


def test_a_check_with_nothing_to_review_is_refused_since_the_image_would_show_nothing(
    results: Path,
) -> None:
    rows = [{**row, "field_status": "accepted"} for row in spreadsheet.read_rows(results)]

    with pytest.raises(ValueError, match="no value to check"):
        spreadsheet.draw(rows)


def test_the_grid_stays_readable_in_upworks_preview() -> None:
    # Upwork checks sharpness at 1000x750 (#60); text shrinks with the image
    # (NN/g, "Big Pictures on Small Screens"). 16 px there is our judgment.
    assert spreadsheet.CELL_SIZE * 1000 / spreadsheet.WIDTH >= 16


def test_the_image_has_the_shape_upwork_asks_for(sheet: spreadsheet.Sheet) -> None:
    # 4:3, at least 1000 px wide, no side over 4000 px (Upwork help, #60).
    width, height = sheet.image.size
    assert width * 3 == height * 4
    assert 1000 <= width <= 4000


# Words a client would have to be a developer to read (tests/test_demo.py, #45).
_DEVELOPER_TERMS = re.compile(
    r"\b(null|none|json|csv|eval|ci|prompt|ocr|llm|api|schema|baseline|pull request|"
    r"sroie|status|needs_review|regression|patch|diff|git|uv|poe|ship\w*|update)\b",
    re.IGNORECASE,
)


def test_the_words_around_the_grid_need_no_developer_to_read_them(
    sheet: spreadsheet.Sheet,
) -> None:
    # The grid's own column names and values may be named: they are what the
    # client filters, and saying "the third column" made the reader count.
    grid = {*spreadsheet.SHOWN, *(cell for row in sheet.cells for cell in row)}
    assert sheet.texts
    for text in sheet.texts:
        plain = " ".join(word for word in text.split() if word.strip(".,:") not in grid)
        assert not _DEVELOPER_TERMS.search(plain), text


@pytest.mark.parametrize(("foreground", "background"), spreadsheet.TEXT_ON)
def test_text_contrasts_with_its_background(
    foreground: tuple[int, int, int], background: tuple[int, int, int]
) -> None:
    # WCAG 2.2 SC 1.4.3: at least 4.5:1 for text.
    assert storyboard.contrast(foreground, background) >= 4.5


# Blocks that touch read as one; 24 px is about one line of the grid (our judgment).
_GAP = 24


def _overlap(one: spreadsheet.Box, other: spreadsheet.Box) -> bool:
    """Whether the boxes come closer than ``_GAP``."""
    return (
        one[0] < other[2] + _GAP
        and other[0] < one[2] + _GAP
        and one[1] < other[3] + _GAP
        and other[1] < one[3] + _GAP
    )


def test_no_part_of_the_image_touches_another_or_leaves_the_image(
    sheet: spreadsheet.Sheet,
) -> None:
    # A green render once hid a stamp over the numbers and overlapping headlines
    # (#45); here a footer first sat flush against the box above it.
    blocks = sheet.blocks
    assert {name for name, _ in blocks} >= {"headline", "label", "grid", "caption", "footer"}
    image = (0, 0, spreadsheet.WIDTH, spreadsheet.HEIGHT)
    for name, box in blocks:
        assert _inside(box, image), f"{name} {box} leaves the image"
    for index, (name, box) in enumerate(blocks):
        for other_name, other in blocks[index + 1 :]:
            assert not _overlap(box, other), f"{name} {box} overlaps {other_name} {other}"
    for name, inner, outer in sheet.nested:
        assert _inside(inner, outer), f"{name} {inner} leaves its box {outer}"


def _inside(inner: spreadsheet.Box, outer: spreadsheet.Box) -> bool:
    left, top, right, bottom = outer
    return left <= inner[0] <= inner[2] <= right and top <= inner[1] <= inner[3] <= bottom


def test_a_cell_too_wide_for_the_image_is_refused_rather_than_overlapping(
    results: Path,
) -> None:
    rows = spreadsheet.read_rows(results)
    rows[0] = {**rows[0], "value": "W" * 200}  # a row of the receipt shown

    with pytest.raises(ValueError, match="does not fit"):
        spreadsheet.draw(rows)


def test_the_committed_image_is_what_the_generator_draws(sheet: spreadsheet.Sheet) -> None:
    with Image.open(spreadsheet.IMAGE) as committed:
        assert committed.tobytes() == sheet.image.tobytes(), (
            f"{spreadsheet.IMAGE} is not what demo/spreadsheet.py draws: run "
            "'uv run poe demo-sheet', look at it and commit it"
        )
