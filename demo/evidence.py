"""What the video shows, taken from the pipeline itself: nothing on screen is typed in by hand.

- each receipt's result, replayed from its recorded answer (``demo/recordings``);
- where each quote sits on the receipt, from OCR's own word boxes;
- the eval's score on the real receipts, with and without the regression
  (``demo/regression.py``), replayed from the private recordings.

A change to the prompt, schema, OCR or model leaves a recording missing, and
the render then stops naming it, instead of filming an old answer.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import tesserocr
from PIL import Image
from pydantic import BaseModel

from core.config import Settings
from core.extract import Pack, extract
from core.ingest import OCR_LANGUAGE, ingest
from core.result import ExtractedField, Status, StrictModel
from core.runlog import new_run_id
from demo.regression import regressed
from evals.recording import RecordingStore, ReplayProvider
from evals.run import run_eval
from evals.scoring import DocumentScore
from evals.sroie import MANIFEST_PATH, load_manifest
from packs.receipt import RECEIPT

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


@dataclass(frozen=True, slots=True)
class GateScore:
    """One eval run, as a client would read it."""

    correct: int
    values: int
    wrong_unchecked: int  # wrong values accepted without review: they reach the client

    @classmethod
    def of(cls, scores: Iterable[DocumentScore]) -> GateScore:
        correct = values = wrong_unchecked = 0
        for score in scores:
            for name, outcome in score.fields.items():
                values += 1
                correct += outcome == "correct"
                wrong = outcome in ("wrong", "unexpected")
                wrong_unchecked += wrong and score.routes[name] == "accepted"
        return cls(correct=correct, values=values, wrong_unchecked=wrong_unchecked)


@dataclass(frozen=True, slots=True)
class GateFacts:
    current: GateScore
    update: GateScore  # with the regression
    documents: int


def replayed(path: Path, settings: Settings) -> Shown:
    """The recorded result for one demo receipt (no key, no cost)."""
    provider = ReplayProvider(
        RecordingStore(DEMO_RECORDINGS),
        provider=settings.provider,
        model=settings.model,
        record_command=f"uv run poe extract --record {DEMO_RECORDINGS} {path}",
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


def gate_facts(settings: Settings) -> GateFacts:
    """The eval on the golden set, replayed with the current prompt and with the regression."""
    ids = [entry.id for entry in load_manifest(MANIFEST_PATH).receipts]

    def score[S: BaseModel](pack: Pack[S]) -> GateScore:
        provider = ReplayProvider(
            RecordingStore(settings.recordings_dir),
            provider=settings.provider,
            model=settings.model,
        )
        run = run_eval(
            ids,
            pack,
            provider,
            golden_dir=settings.sroie_dir,
            tessdata_dir=settings.tessdata_dir,
            run_id=new_run_id(),
            provider_name=settings.provider,
            max_retries=settings.max_retries,
        )
        return GateScore.of(run.scores)

    return GateFacts(current=score(RECEIPT), update=score(regressed(RECEIPT)), documents=len(ids))
