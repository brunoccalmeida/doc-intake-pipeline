"""The run log: one JSON line per document, saying what happened and what it cost.

Clients ask "how much per document?" and "what happened with this one?"
(``docs/ARCHITECTURE.md`` D5). Each extraction emits one ``RunLogEntry`` as a
JSON line on the ``core.runlog`` logger, at INFO:

- ids (run, document), pack, provider, the models that answered;
- outcome: status and the validation or citation errors, which name fields
  and rules but never the offending input (``core.extract._describe``);
- usage: calls, retries, tokens, latency, and cost in exact USD (``Decimal``,
  serialized as text so no float rounding creeps in).

Never document content (AGENTS.md invariant 6): no page text, values or quotes.

This module only emits; where the lines go is the application's choice
(``scripts/logs.py``). A library adds no handlers (Python logging cookbook,
"Patterns to avoid").
"""

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from core.extract import Pack, extract
from core.ingest import Document
from core.llm import LLMProvider, LLMResponse, Metered
from core.pricing import cost_usd
from core.result import ExtractionResult, Status, StrictModel

RUN_LOGGER = __name__

_logger = logging.getLogger(RUN_LOGGER)

type Count = Annotated[int, Field(ge=0)]


class RunLogEntry(StrictModel, frozen=True):
    """One document of one run; see the module docstring for what it holds and why."""

    timestamp: datetime
    run_id: str
    document_id: str
    pack: str
    provider: str
    models: tuple[str, ...]
    status: Status
    errors: list[str]
    calls: Count
    retries: Count
    input_tokens: Count
    output_tokens: Count
    latency_ms: Count
    cost_usd: Decimal


def new_run_id() -> str:
    """A UUIDv7: unique, and ordered by creation time, so runs sort in the log."""
    return str(uuid.uuid7())


def extract_logged[S: BaseModel](
    document: Document,
    pack: Pack[S],
    provider: LLMProvider,
    *,
    document_id: str,
    run_id: str,
    provider_name: str,
    max_retries: int = 2,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[ExtractionResult[S], RunLogEntry]:
    """``extract`` the document, then log and return its entry.

    Latency is the extraction's (every call, retries included), not reading
    the file. A model without a price raises ``UnknownModelPriceError`` and
    nothing is logged: an entry costing zero would look free.
    """
    metered = Metered(provider)
    started = clock()
    result = extract(document, pack, metered, max_retries=max_retries)
    elapsed = clock() - started
    entry = RunLogEntry(
        timestamp=datetime.now(UTC),
        run_id=run_id,
        document_id=document_id,
        pack=pack.name,
        provider=provider_name,
        models=tuple(sorted({r.model for r in metered.responses})),
        status=result.status,
        errors=result.errors,
        calls=len(metered.responses),
        retries=max(len(metered.responses) - 1, 0),
        input_tokens=sum(r.input_tokens for r in metered.responses),
        output_tokens=sum(r.output_tokens for r in metered.responses),
        latency_ms=round(elapsed * 1000),
        cost_usd=_cost(metered.responses),
    )
    _emit(entry)
    return result, entry


def log_unreadable(
    error: Exception, *, pack_name: str, document_id: str, run_id: str, provider_name: str
) -> RunLogEntry:
    """Log a document that could not be read: failed, no call made, so no cost.

    Only the error's class is logged: its message names the file, and a file
    name can be a client's.
    """
    entry = RunLogEntry(
        timestamp=datetime.now(UTC),
        run_id=run_id,
        document_id=document_id,
        pack=pack_name,
        provider=provider_name,
        models=(),
        status="failed",
        errors=[type(error).__name__],
        calls=0,
        retries=0,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        cost_usd=Decimal(0),
    )
    _emit(entry)
    return entry


def _emit(entry: RunLogEntry) -> None:
    _logger.info(entry.model_dump_json())


def _cost(responses: Sequence[LLMResponse]) -> Decimal:
    return sum(
        (
            cost_usd(r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens)
            for r in responses
        ),
        Decimal(0),
    )
