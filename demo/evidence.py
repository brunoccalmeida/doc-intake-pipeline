"""What the video shows, taken from the pipeline itself: nothing on screen is typed in by hand.

- each receipt's result, replayed from its recorded answer (``demo/recordings``);
- where each quote sits on the receipt, from OCR's own word boxes.

A change to the prompt, schema, OCR or model leaves a recording missing, and
the render then stops naming it, instead of filming an old answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import tesserocr
from PIL import Image

from doc_intake.core.config import Settings
from doc_intake.core.extract import extract
from doc_intake.core.ingest import OCR_LANGUAGE, ingest
from doc_intake.core.result import ExtractedField, Status, StrictModel
from doc_intake.packs.receipt import RECEIPT
from evals.recording import RecordingStore, ReplayProvider

DEMO_RECORDINGS = Path("demo/recordings")

type Box = tuple[int, int, int, int]  # left, top, right, bottom, in the receipt's pixels
type Word = tuple[str, Box]


class Shown(StrictModel, frozen=True):
    """A result as the video shows it: every value as its JSON text.

    A Decimal and a date are strings in JSON, so one type reads any pack's
    fields without knowing the pack.
    """

    status: Status
    # Not optional: a failed result has no fields, and the video has nothing to show.
    fields: dict[str, ExtractedField[str]]
    errors: list[str]
    review: list[str]


@dataclass(frozen=True, slots=True)
class Evidence:
    """One receipt on screen: the image, its result, and the boxes of each text quote."""

    image: Path
    result: Shown
    # Per field, one box per printed line its quote covers; a field read from
    # the image only (or empty) has none.
    boxes: dict[str, list[Box]]


def replayed(path: Path, settings: Settings) -> Shown:
    """The recorded result for one demo receipt (no key, no cost)."""
    provider = ReplayProvider(
        RecordingStore(DEMO_RECORDINGS),
        provider=settings.provider,
        model=settings.model,
        # With the provider and model stated: a .env picking another model
        # would record under another key, and the render would still fail.
        record_command=(
            f"DOC_INTAKE_PROVIDER={settings.provider} DOC_INTAKE_CLAUDE_MODEL={settings.model} "
            f"uv run poe extract --record {DEMO_RECORDINGS} {path}"
        ),
    )
    document = ingest(path, tessdata_dir=settings.tessdata_dir)
    result = extract(document, RECEIPT, provider, max_retries=settings.max_retries)
    return Shown.model_validate_json(result.model_dump_json())


def ocr_words(path: Path, tessdata_dir: Path) -> list[Word]:
    """Every word OCR reads on the image, with its box, in reading order."""
    with (
        Image.open(path) as image,
        tesserocr.PyTessBaseAPI(path=str(tessdata_dir), lang=OCR_LANGUAGE) as api,
    ):
        api.SetImage(image)
        api.Recognize()
        return [
            (word.GetUTF8Text(tesserocr.RIL.WORD), word.BoundingBox(tesserocr.RIL.WORD))
            for word in tesserocr.iterate_level(api.GetIterator(), tesserocr.RIL.WORD)
        ]


def quote_boxes(words: Sequence[Word], quote: str) -> list[Box]:
    """The boxes of the first run of words equal to ``quote``, one per printed line.

    Empty when the quote is not in what OCR read: a quote from the image only.
    """
    wanted = quote.split()
    texts = [text for text, _ in words]
    for start in range(len(words) - len(wanted) + 1):
        if texts[start : start + len(wanted)] == wanted:
            return _lines([box for _, box in words[start : start + len(wanted)]])
    return []


def _lines(boxes: list[Box]) -> list[Box]:
    """Join word boxes into one box per line.

    A word whose top is below the middle of the line so far starts a new line.
    """
    lines: list[Box] = []
    for left, top, right, bottom in boxes:
        if lines and top < (lines[-1][1] + lines[-1][3]) / 2:
            line = lines[-1]
            lines[-1] = (
                min(line[0], left),
                min(line[1], top),
                max(line[2], right),
                max(line[3], bottom),
            )
        else:
            lines.append((left, top, right, bottom))
    return lines


def receipt_evidence(path: Path, settings: Settings) -> Evidence:
    result = replayed(path, settings)
    words = ocr_words(path, settings.tessdata_dir)
    boxes = {
        name: quote_boxes(words, field.citation.quote)
        for name, field in result.fields.items()
        if field.citation is not None and field.citation.source == "text"
    }
    return Evidence(image=path, result=result, boxes=boxes)
