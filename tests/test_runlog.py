"""The run log: one JSON line per document, with usage, cost and outcome, never content.

A scripted fake provider answers (AGENTS.md invariant 4). The document's lines
are distinctive on purpose, so the no-content test can look for each of them.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from core.extract import Pack
from core.ingest import Document, EmptyDocumentError, PageText
from core.llm import LLMRequest, LLMResponse
from core.pricing import UnknownModelPriceError
from core.result import ExtractedField, ExtractionResult, StrictModel
from core.runlog import RUN_LOGGER, RunLogEntry, extract_logged, log_unreadable, new_run_id

PAGE_TEXT = "ZEPHYR QUILL TRADING\nLOT 77, JALAN SEROJA\nTOTAL RM 31.40"
DOCUMENT = Document(pages=(PageText(number=1, text=PAGE_TEXT, source="ocr"),))


class Sale(StrictModel, frozen=True):
    company: ExtractedField[str]
    total: ExtractedField[Decimal]


PACK = Pack(name="sale", schema=Sale, instructions="Read the seller and the amount paid.")


def cited(value: object, quote: str) -> dict[str, Any]:
    return {"value": value, "citation": {"page": 1, "quote": quote}, "reason": None}


VALID = json.dumps(
    {
        "company": cited("ZEPHYR QUILL TRADING", "ZEPHYR QUILL TRADING"),
        "total": cited("31.40", "TOTAL RM 31.40"),
    }
)
# Invalid on purpose (a value without its citation), and full of document text:
# the validation errors must not carry any of it into the log.
INVALID = json.dumps(
    {
        "company": {"value": "ZEPHYR QUILL TRADING", "citation": None, "reason": None},
        "total": cited("31.40", "TOTAL RM 31.40"),
    }
)
# A quote the page does not hold: the result needs review.
MISQUOTED = json.dumps(
    {
        "company": cited("ZEPHYR QUILL TRADING", "LOT 77, JALAN SEROJA ZEPHYR"),
        "total": cited("31.40", "TOTAL RM 31.40"),
    }
)


@dataclass
class FakeProvider:
    """Returns the scripted texts in order, answering as ``model``."""

    replies: list[str]
    model: str = "claude-opus-5-5"
    calls: int = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResponse(text=text, input_tokens=1_000, output_tokens=200, model=self.model)


@dataclass
class FakeClock:
    """Each read advances by ``step`` seconds, so a timed block lasts exactly ``step``."""

    step: float
    now: float = 100.0
    reads: list[float] = field(default_factory=list[float])

    def __call__(self) -> float:
        self.reads.append(self.now)
        self.now += self.step
        return self.reads[-1]


def run(
    replies: list[str], *, model: str = "claude-opus-5-5", max_retries: int = 2
) -> tuple[ExtractionResult[Sale], RunLogEntry]:
    return extract_logged(
        DOCUMENT,
        PACK,
        FakeProvider(replies, model=model),
        document_id="doc-1",
        run_id="run-1",
        provider_name="fake",
        max_retries=max_retries,
        clock=FakeClock(step=0.25),
    )


def test_a_valid_answer_is_logged_with_its_usage_cost_and_latency() -> None:
    result, entry = run([VALID])

    assert result.status == "ok"
    assert entry.run_id == "run-1"
    assert entry.document_id == "doc-1"
    assert entry.pack == "sale"
    assert entry.provider == "fake"
    assert entry.models == ("claude-opus-5-5",)
    assert entry.status == "ok"
    assert entry.errors == []
    assert (entry.calls, entry.retries) == (1, 0)
    assert (entry.input_tokens, entry.output_tokens) == (1_000, 200)
    assert entry.cost_usd == Decimal("0.008")  # 1000 x $4/M + 200 x $20/M
    assert entry.latency_ms == 250


def test_each_retry_is_counted_and_its_tokens_are_paid() -> None:
    _, entry = run([INVALID, VALID])

    assert entry.status == "ok"
    assert (entry.calls, entry.retries) == (2, 1)
    assert (entry.input_tokens, entry.output_tokens) == (2_000, 400)
    assert entry.cost_usd == Decimal("0.016")


def test_a_failure_is_logged_with_its_validation_errors() -> None:
    _, entry = run([INVALID], max_retries=1)

    assert entry.status == "failed"
    assert (entry.calls, entry.retries) == (2, 1)
    assert entry.errors == ["company: Value error, a value requires a citation"]


def test_one_line_per_document(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)
    run([VALID])
    run([INVALID, VALID])

    assert len([r for r in caplog.records if r.name == RUN_LOGGER]) == 2


def test_the_line_is_json_with_cost_as_exact_text_and_an_iso_timestamp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)
    run([VALID])

    [record] = [r for r in caplog.records if r.name == RUN_LOGGER]
    assert record.levelno == logging.INFO
    line = json.loads(record.getMessage())
    assert line["cost_usd"] == "0.008"  # text, not a float: Decimal survives the round trip
    assert datetime.fromisoformat(line["timestamp"]).tzinfo is not None
    assert line["document_id"] == "doc-1"


@pytest.mark.parametrize(
    "replies", [[VALID], [INVALID], [MISQUOTED]], ids=["ok", "failed", "review"]
)
def test_the_line_holds_no_document_text(
    caplog: pytest.LogCaptureFixture, replies: list[str]
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)
    run(replies, max_retries=0)

    [record] = [r for r in caplog.records if r.name == RUN_LOGGER]
    message = record.getMessage()
    for text in [*PAGE_TEXT.splitlines(), "ZEPHYR", "SEROJA", "31.40"]:
        assert text not in message


def test_a_model_without_a_price_fails_loudly_instead_of_logging_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)

    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        run([VALID], model="model-x")

    assert not [r for r in caplog.records if r.name == RUN_LOGGER]


def test_an_unreadable_document_is_logged_as_failed_by_error_class_at_no_cost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)

    # The message names the file, which may be a client's: only the class is logged.
    error = EmptyDocumentError("no text in ZEPHYR-QUILL-receipt.jpg")
    entry = log_unreadable(
        error, pack_name="sale", document_id="doc-2", run_id="run-1", provider_name="fake"
    )

    assert entry.status == "failed"
    assert entry.errors == ["EmptyDocumentError"]
    assert (entry.calls, entry.retries, entry.input_tokens, entry.output_tokens) == (0, 0, 0, 0)
    assert entry.cost_usd == 0
    assert entry.models == ()
    [record] = [r for r in caplog.records if r.name == RUN_LOGGER]
    assert json.loads(record.getMessage())["document_id"] == "doc-2"
    assert "ZEPHYR" not in record.getMessage()


def test_run_ids_are_unique_and_sort_by_creation_time() -> None:
    ids = [new_run_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids)
