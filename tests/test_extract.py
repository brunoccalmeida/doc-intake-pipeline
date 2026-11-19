"""Extraction engine: provider call, schema validation, bounded retry, citation check.

Every test uses a scripted fake provider (AGENTS.md invariant 4: no network,
no API cost). The fake records each request, so a test can assert what the
engine asked for, not only what it returned.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from pydantic import Field

from core.extract import Pack, extract
from core.ingest import Document, PageText
from core.llm import LLMRequest, LLMResponse
from core.result import ExtractedField, StrictModel

PAGE_1 = "ACME TRADING SDN BHD\nNO. 12, JALAN MAJU\nTOTAL   RM 9.00"
PAGE_2 = "THANK YOU\nPLEASE COME AGAIN"
DOCUMENT = Document(
    pages=(
        PageText(number=1, text=PAGE_1, source="text_layer"),
        PageText(number=2, text=PAGE_2, source="ocr"),
    )
)


class Sale(StrictModel, frozen=True):
    """A minimal pack schema: one text field and one money field."""

    company: ExtractedField[str]
    total: ExtractedField[Decimal]


PACK = Pack(name="sale", schema=Sale, instructions="Read the seller and the amount paid.")


@dataclass
class FakeProvider:
    """Returns the scripted texts in order and records every request."""

    replies: list[str]
    requests: list[LLMRequest] = field(default_factory=list[LLMRequest])

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        text = self.replies[min(len(self.requests), len(self.replies)) - 1]
        return LLMResponse(text=text, input_tokens=100, output_tokens=20, model="fake-1")


def cited(value: object, quote: str, page: int = 1, source: str = "text") -> dict[str, Any]:
    return {
        "value": value,
        "citation": {"page": page, "source": source, "quote": quote},
        "reason": None,
    }


def sale_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "company": cited("ACME TRADING SDN BHD", "ACME TRADING SDN BHD"),
        "total": cited("9.00", "TOTAL   RM 9.00"),
    }
    fields.update(overrides)
    return json.dumps(fields)


def test_valid_response_is_ok_after_one_call() -> None:
    provider = FakeProvider([sale_json()])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"
    assert result.fields is not None
    assert result.fields.total.value == Decimal("9.00")
    assert len(provider.requests) == 1


def test_request_carries_every_page_the_instructions_and_the_schema() -> None:
    provider = FakeProvider([sale_json()])
    extract(DOCUMENT, PACK, provider)
    request = provider.requests[0]
    assert PAGE_1 in request.prompt
    assert PAGE_2 in request.prompt
    assert "Read the seller and the amount paid." in request.instructions
    assert request.output_schema is Sale
    assert request.schema_name == "sale"


def test_field_descriptions_reach_the_instructions() -> None:
    """A provider may drop descriptions from the schema; the instructions keep them."""

    class WithDescription(StrictModel, frozen=True):
        company: ExtractedField[str] = Field(description="Name of the seller as printed.")

    provider = FakeProvider([json.dumps({"company": cited("ACME", "ACME")})])
    extract(DOCUMENT, Pack(name="d", schema=WithDescription, instructions="x"), provider)
    assert "company: Name of the seller as printed." in provider.requests[0].instructions


def test_malformed_then_valid_is_ok_and_the_retry_names_the_error() -> None:
    provider = FakeProvider(['{"company": ', sale_json()])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"
    assert len(provider.requests) == 2
    retry = provider.requests[1].prompt
    assert "Invalid JSON" in retry
    assert '{"company": ' in retry, "the retry shows the rejected answer"


def test_schema_violation_then_valid_is_ok_and_the_retry_names_the_field() -> None:
    no_citation = sale_json(total={"value": "9.00", "citation": None, "reason": None})
    provider = FakeProvider([no_citation, sale_json()])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"
    assert "total" in provider.requests[1].prompt
    assert "a value requires a citation" in provider.requests[1].prompt


def test_always_malformed_fails_after_the_limit_with_no_partial_result() -> None:
    provider = FakeProvider(["not json"])
    result = extract(DOCUMENT, PACK, provider, max_retries=2)
    assert result.status == "failed"
    assert result.fields is None
    assert len(provider.requests) == 3, "one call plus two retries"
    assert any("Invalid JSON" in error for error in result.errors)


def test_zero_retries_means_a_single_call() -> None:
    provider = FakeProvider(["not json"])
    result = extract(DOCUMENT, PACK, provider, max_retries=0)
    assert result.status == "failed"
    assert len(provider.requests) == 1


def test_negative_retries_are_refused() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        extract(DOCUMENT, PACK, FakeProvider([sale_json()]), max_retries=-1)


def test_failure_errors_do_not_echo_document_content() -> None:
    """Errors end up in logs; they name the field and the rule, never the value."""
    leaked = "SECRET-CUSTOMER-NAME-1234"
    provider = FakeProvider([sale_json(total=cited(leaked, "TOTAL   RM 9.00"))])
    result = extract(DOCUMENT, PACK, provider, max_retries=0)
    assert result.status == "failed"
    assert result.errors
    assert all(leaked not in error for error in result.errors)


def test_fabricated_quote_downgrades_to_needs_review() -> None:
    provider = FakeProvider([sale_json(total=cited("9.00", "GRAND TOTAL RM 9.00"))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.fields is not None, "the fields stay for the reviewer"
    assert result.errors == ["total: quote not found on page 1"]


def test_quote_from_another_page_downgrades_to_needs_review() -> None:
    provider = FakeProvider([sale_json(company=cited("ACME TRADING SDN BHD", "ACME", page=2))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.errors == ["company: quote not found on page 2"]


def test_citation_to_a_missing_page_downgrades_to_needs_review() -> None:
    provider = FakeProvider([sale_json(company=cited("ACME TRADING SDN BHD", "ACME", page=3))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.errors == ["company: cites page 3, but the document has 2 pages"]


def test_quote_matches_across_a_line_break_written_as_a_space() -> None:
    """Models often copy a multi-line passage as one line; only whitespace may differ."""
    quote = "ACME TRADING SDN BHD NO. 12, JALAN MAJU"
    provider = FakeProvider([sale_json(company=cited("ACME TRADING SDN BHD", quote))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"


def test_quote_with_changed_letters_is_not_a_match() -> None:
    provider = FakeProvider([sale_json(company=cited("ACME", "Acme Trading Sdn Bhd"))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"


def test_empty_field_needs_no_citation_check() -> None:
    empty = {"value": None, "citation": None, "reason": "no amount printed"}
    provider = FakeProvider([sale_json(total=empty)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"
