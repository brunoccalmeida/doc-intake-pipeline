"""Run the pipeline over golden documents and score each one, metering every call.

Each document goes through the same path as production (``ingest`` then
``extract``), so the eval measures the pipeline, not a shortcut. A document
that cannot be read is scored as failed, never skipped: skipping it would
raise the accuracy by hiding the failure. What is not about the document
stops the run instead: missing OCR data, a missing golden record or
recording, a transport error.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from core.extract import Pack, extract
from core.ingest import IngestError, OcrDataMissingError, ingest
from core.llm import LLMProvider, Metered
from core.pricing import cost_usd
from evals.scoring import DocumentScore, score_document


@dataclass(frozen=True, slots=True)
class Usage:
    """Calls, tokens and cost of a run; ``models`` are those that actually answered."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalRun:
    scores: list[DocumentScore]
    usage: Usage


def run_eval[S: BaseModel](
    document_ids: Sequence[str],
    pack: Pack[S],
    provider: LLMProvider,
    *,
    golden_dir: Path,
    tessdata_dir: Path,
    max_retries: int = 2,
) -> EvalRun:
    """Score ``<id>.jpg`` against ``<id>.json`` in ``golden_dir`` for every id."""
    metered = Metered(provider)
    scores: list[DocumentScore] = []
    for document_id in document_ids:
        golden = pack.schema.model_validate_json(
            (golden_dir / f"{document_id}.json").read_text(encoding="utf-8")
        )
        try:
            document = ingest(golden_dir / f"{document_id}.jpg", tessdata_dir=tessdata_dir)
        except OcrDataMissingError:
            raise
        except IngestError as error:
            scores.append(score_document(document_id, golden, type(error).__name__))
            continue
        result = extract(document, pack, metered, max_retries=max_retries)
        scores.append(score_document(document_id, golden, result))
    return EvalRun(scores=scores, usage=_usage(metered))


def _usage(metered: Metered) -> Usage:
    responses = metered.responses
    return Usage(
        calls=len(responses),
        input_tokens=sum(r.input_tokens for r in responses),
        output_tokens=sum(r.output_tokens for r in responses),
        cost_usd=sum(
            (
                cost_usd(r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens)
                for r in responses
            ),
            Decimal(0),
        ),
        models=tuple(sorted({r.model for r in responses})),
    )
