"""Run the pipeline over golden documents and score each one, logging every document.

Each document goes through the same path as production (``ingest`` then
``extract``, logged by ``core.runlog``), so the eval measures the pipeline,
not a shortcut. A document that cannot be read is scored as failed, never
skipped: skipping it would raise the accuracy by hiding the failure. What is
not about the document stops the run instead: missing OCR data, a missing
golden record or recording, a transport error.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from core.extract import Pack
from core.ingest import IngestError, OcrDataMissingError, ingest
from core.llm import LLMProvider
from core.runlog import RunLogEntry, extract_logged, log_unreadable
from evals.scoring import DocumentScore, score_document

# Averages are rounded to a millionth of a dollar: the cheapest token in the
# price table costs $0.000004, so this keeps a single token visible while
# dropping the endless digits of a division such as 0.016 / 3.
_MICRODOLLAR = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Usage:
    """Documents, calls, tokens and cost of a run; ``models`` are those that answered."""

    documents: int
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    models: tuple[str, ...]

    @classmethod
    def of(cls, entries: Sequence[RunLogEntry]) -> Usage:
        return cls(
            documents=len(entries),
            calls=sum(e.calls for e in entries),
            input_tokens=sum(e.input_tokens for e in entries),
            output_tokens=sum(e.output_tokens for e in entries),
            cost_usd=sum((e.cost_usd for e in entries), Decimal(0)),
            models=tuple(sorted({m for e in entries for m in e.models})),
        )

    @property
    def average_cost_usd(self) -> Decimal | None:
        """Cost per document, unreadable ones included (they count, at no cost).

        ``None`` for a run without documents: there is no average to show.
        Rounded half-even, ``Decimal``'s default.
        """
        if not self.documents:
            return None
        return (self.cost_usd / self.documents).quantize(_MICRODOLLAR)


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
    run_id: str,
    provider_name: str,
    max_retries: int = 2,
) -> EvalRun:
    """Score ``<id>.jpg`` against ``<id>.json`` in ``golden_dir`` for every id."""
    scores: list[DocumentScore] = []
    entries: list[RunLogEntry] = []
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
            entries.append(
                log_unreadable(
                    error,
                    pack_name=pack.name,
                    document_id=document_id,
                    run_id=run_id,
                    provider_name=provider_name,
                )
            )
            continue
        result, entry = extract_logged(
            document,
            pack,
            provider,
            document_id=document_id,
            run_id=run_id,
            provider_name=provider_name,
            max_retries=max_retries,
        )
        scores.append(score_document(document_id, golden, result))
        entries.append(entry)
    return EvalRun(scores=scores, usage=Usage.of(entries))
