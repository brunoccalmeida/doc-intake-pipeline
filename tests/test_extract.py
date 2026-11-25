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

from doc_intake.core.extract import Pack, Rule, extract
from doc_intake.core.ingest import Document, PageImage, PageText
from doc_intake.core.llm import ImageInput, LLMRequest, LLMResponse
from doc_intake.core.result import ExtractedField, StrictModel

PAGE_1 = "ACME TRADING SDN BHD\nNO. 12, JALAN MAJU\nTOTAL   RM 9.00"
PAGE_2 = "THANK YOU\nPLEASE COME AGAIN"
PAGE_2_IMAGE = PageImage(media_type="image/png", data=b"page 2 png")
DOCUMENT = Document(
    pages=(
        PageText(number=1, text=PAGE_1, source="text_layer", image=None),
        PageText(number=2, text=PAGE_2, source="ocr", image=PAGE_2_IMAGE),
    )
)


class Sale(StrictModel, frozen=True):
    """A minimal pack schema: one text field and one money field."""

    company: ExtractedField[str]
    total: ExtractedField[Decimal]


PACK = Pack(
    name="sale",
    schema=Sale,
    instructions="Read the seller and the amount paid.",
    printed=frozenset({"company"}),
)


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
    extract(
        DOCUMENT,
        Pack(name="d", schema=WithDescription, instructions="x", printed=frozenset()),
        provider,
    )
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
    assert result.review == ["total"]


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


def test_request_carries_the_image_of_every_ocr_page_and_only_those() -> None:
    # Page 1 is a text layer (exact text, no image); page 2 was read by OCR.
    provider = FakeProvider([sale_json()])
    extract(DOCUMENT, PACK, provider)
    assert provider.requests[0].images == (
        ImageInput(label="Image of page 2:", media_type="image/png", data=b"page 2 png"),
    )


def test_retry_sends_the_images_again() -> None:
    # Each request is self-contained (D10): a retry has no conversation history.
    provider = FakeProvider(["not json", sale_json()])
    extract(DOCUMENT, PACK, provider)
    assert provider.requests[1].images == provider.requests[0].images


def test_text_value_must_be_inside_its_quote() -> None:
    # D11: a text value is the text as read; commas the page does not print
    # (seen in #20) make a value that is nowhere in the document.
    added_comma = cited("ACME TRADING SDN BHD, NO. 12", "ACME TRADING SDN BHD\nNO. 12")
    provider = FakeProvider([sale_json(company=added_comma)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.errors == ["company: value is not the text of its quote"]


def test_text_value_inside_a_longer_quote_is_ok() -> None:
    # A quote is often the whole printed line around the value.
    provider = FakeProvider([sale_json(company=cited("ACME", "ACME TRADING SDN BHD"))])
    assert extract(DOCUMENT, PACK, provider).status == "ok"


class Coded(StrictModel, frozen=True):
    """A printed field and a normalised one, like a receipt's company and currency."""

    company: ExtractedField[str]
    currency: ExtractedField[str]


CODED = Pack(name="coded", schema=Coded, instructions="x", printed=frozenset({"company"}))


def test_normalised_text_value_may_differ_from_its_quote() -> None:
    # The pack asks for an ISO code where "RM" is printed: only "as printed"
    # fields are held to their quote (review of #26).
    answer = json.dumps(
        {"company": cited("ACME", "ACME TRADING SDN BHD"), "currency": cited("MYR", "RM 9.00")}
    )
    result = extract(DOCUMENT, CODED, FakeProvider([answer]))
    assert result.status == "ok"


def test_printed_field_is_still_held_to_its_quote_beside_a_normalised_one() -> None:
    answer = json.dumps(
        {"company": cited("ACME CO", "ACME TRADING SDN BHD"), "currency": cited("MYR", "RM 9.00")}
    )
    result = extract(DOCUMENT, CODED, FakeProvider([answer]))
    assert result.errors == ["company: value is not the text of its quote"]


def test_instructions_name_the_fields_read_as_printed() -> None:
    provider = FakeProvider([sale_json()])
    extract(DOCUMENT, PACK, provider)
    assert "Fields read as printed: company." in provider.requests[0].instructions


def test_pack_refuses_a_printed_field_its_schema_lacks() -> None:
    with pytest.raises(ValueError, match="printed fields not in the schema: seller"):
        Pack(name="x", schema=Sale, instructions="x", printed=frozenset({"seller"}))


def test_value_read_from_the_page_image_goes_to_review() -> None:
    # The engine can check a quote against the page text, not against pixels:
    # a person checks it (AWS A2I pattern: an activation condition, D12).
    from_image = cited("THANK YOU", "THANK YOU", page=2, source="image")
    provider = FakeProvider([sale_json(company=from_image)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.fields is not None, "the fields stay for the reviewer"
    assert result.errors == ["company: read from the image of page 2; check it on the page"]
    assert result.review == ["company"]


def test_review_names_every_flagged_field_in_schema_order() -> None:
    from_image = cited("THANK YOU", "THANK YOU", page=2, source="image")
    fabricated = cited("9.00", "GRAND TOTAL RM 9.00")
    provider = FakeProvider([sale_json(company=from_image, total=fabricated)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.review == ["company", "total"]


def test_ok_result_names_no_field_to_review() -> None:
    assert extract(DOCUMENT, PACK, FakeProvider([sale_json()])).review == []


def test_image_quote_must_still_hold_the_whole_text_value() -> None:
    from_image = cited("THANK YOU AGAIN", "THANK YOU", page=2, source="image")
    provider = FakeProvider([sale_json(company=from_image)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.errors == ["company: value is not the text of its quote"]


def test_image_citation_of_a_page_without_image_is_flagged() -> None:
    from_image = cited("ACME TRADING SDN BHD", "ACME TRADING SDN BHD", source="image")
    provider = FakeProvider([sale_json(company=from_image)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "needs_review"
    assert result.errors == ["company: cites the image of page 1, which was not sent"]


def test_a_field_accepted_from_the_image_skips_only_the_image_review() -> None:
    # An acceptance policy (#65, D22) vouches for image reading, nothing else.
    from_image = cited("THANK YOU", "THANK YOU", page=2, source="image")
    provider = FakeProvider([sale_json(company=from_image)])
    result = extract(DOCUMENT, PACK, provider, accept_from_image=frozenset({"company"}))
    assert (result.status, result.errors, result.review) == ("ok", [], [])


@pytest.mark.parametrize(
    ("company", "problem"),
    [
        (cited("THANK YOU AGAIN", "THANK YOU", page=2, source="image"), "value is not the text"),
        (cited("ACME", "ACME", source="image"), "cites the image of page 1, which was not sent"),
        (cited("ACME", "ACME CORP"), "quote not found on page 1"),
    ],
)
def test_an_accepted_field_is_still_checked_for_every_other_problem(
    company: dict[str, object], problem: str
) -> None:
    provider = FakeProvider([sale_json(company=company)])
    result = extract(DOCUMENT, PACK, provider, accept_from_image=frozenset({"company"}))
    assert result.review == ["company"]
    assert result.errors[0].startswith(f"company: {problem}")


def test_accepting_a_field_the_schema_lacks_fails_before_any_call() -> None:
    provider = FakeProvider([])
    with pytest.raises(ValueError, match="seller"):
        extract(DOCUMENT, PACK, provider, accept_from_image=frozenset({"seller"}))
    assert provider.requests == []


def test_empty_field_needs_no_citation_check() -> None:
    empty = {"value": None, "citation": None, "reason": "no amount printed"}
    provider = FakeProvider([sale_json(total=empty)])
    result = extract(DOCUMENT, PACK, provider)
    assert result.status == "ok"


# Money must be read, not computed (#66): a value the rule checks could
# otherwise be derived from the others, and the rule would check itself.
@pytest.mark.parametrize(
    ("value", "quote"),
    [
        ("9", "TOTAL   RM 9.00"),
        ("9.00", "TOTAL   RM 9.00"),
    ],
)
def test_money_value_printed_in_its_quote_is_accepted(value: str, quote: str) -> None:
    provider = FakeProvider([sale_json(total=cited(value, quote))])
    assert extract(DOCUMENT, PACK, provider).status == "ok"


def test_money_value_missing_from_its_quote_goes_to_review() -> None:
    # 8.20 is not printed in the quote: a computed or misplaced value.
    provider = FakeProvider([sale_json(total=cited("8.20", "TOTAL   RM 9.00"))])
    result = extract(DOCUMENT, PACK, provider)
    assert result.review == ["total"]
    assert result.errors == ["total: amount is not a number printed in its quote"]


class Bill(StrictModel, frozen=True):
    """Amounts a consistency rule ties together; rounding may be negative."""

    net: ExtractedField[Decimal]
    tax: ExtractedField[Decimal]
    rounding: ExtractedField[Decimal]
    total: ExtractedField[Decimal]


def _adds_up(bill: Bill) -> bool | None:
    net, tax, total = bill.net.value, bill.tax.value, bill.total.value
    if net is None or tax is None or total is None:
        return None
    return net + tax + (bill.rounding.value or 0) == total


ADDS_UP = Rule[Bill](
    name="amounts_add_up",
    description="net + tax + rounding must equal total",
    fields=("net", "tax", "rounding", "total"),
    holds=_adds_up,
)
BILL_PACK = Pack(
    name="bill",
    schema=Bill,
    instructions="Read the amounts.",
    printed=frozenset(),
    rules=(ADDS_UP,),
)
BILL_PAGE = "NET 7.74\nTAX 0.46\nROUNDING -0.02\nTOTAL 8.18\nTOTAL 8.20\nTAX 0.48"
BILL_DOCUMENT = Document(
    pages=(PageText(number=1, text=BILL_PAGE, source="text_layer", image=None),)
)
NO_VALUE = {"value": None, "citation": None, "reason": "not printed"}


def bill_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "net": cited("7.74", "NET 7.74"),
        "tax": cited("0.46", "TAX 0.46"),
        "rounding": cited("-0.02", "ROUNDING -0.02"),
        "total": cited("8.18", "TOTAL 8.18"),
    }
    fields.update(overrides)
    return json.dumps(fields)


def test_amounts_that_add_up_are_ok() -> None:
    # The sign of a negative amount is conversion: the quote prints it either way.
    result = extract(BILL_DOCUMENT, BILL_PACK, FakeProvider([bill_json()]))
    assert (result.status, result.errors) == ("ok", [])


def test_a_failed_rule_sends_its_fields_to_review_naming_the_rule() -> None:
    provider = FakeProvider([bill_json(total=cited("8.20", "TOTAL 8.20"))])
    result = extract(BILL_DOCUMENT, BILL_PACK, provider)
    assert result.status == "needs_review"
    assert result.review == ["net", "tax", "rounding", "total"]
    rule = "fails rule amounts_add_up: net + tax + rounding must equal total"
    assert result.errors == [f"{name}: {rule}" for name in result.review]


def test_a_rule_message_carries_no_document_value() -> None:
    # Errors reach logs and the review queue (AGENTS.md invariant 6).
    provider = FakeProvider([bill_json(total=cited("8.20", "TOTAL 8.20"))])
    errors = " ".join(extract(BILL_DOCUMENT, BILL_PACK, provider).errors)
    assert not any(amount in errors for amount in ("7.74", "0.46", "8.20", "8.18"))


def test_a_rule_that_does_not_apply_sends_nothing_to_review() -> None:
    provider = FakeProvider([bill_json(net=NO_VALUE, total=cited("8.20", "TOTAL 8.20"))])
    result = extract(BILL_DOCUMENT, BILL_PACK, provider)
    assert (result.status, result.review) == ("ok", [])


def test_a_field_with_a_citation_problem_also_names_the_failed_rule() -> None:
    # One error per field (the review queue keys notes by field), both problems in it.
    provider = FakeProvider([bill_json(tax=cited("0.48", "TAX 0.46"))])
    result = extract(BILL_DOCUMENT, BILL_PACK, provider)
    assert result.errors[1] == (
        "tax: amount is not a number printed in its quote; "
        "fails rule amounts_add_up: net + tax + rounding must equal total"
    )
    assert len(result.errors) == len(result.review) == 4


def test_a_failed_rule_overrides_acceptance_from_the_image() -> None:
    # An acceptance policy (D22) vouches for image reading, not for the arithmetic.
    image_document = Document(
        pages=(PageText(number=1, text=BILL_PAGE, source="ocr", image=PAGE_2_IMAGE),)
    )
    from_image = cited("8.30", "TOTAL 8.30", source="image")
    provider = FakeProvider([bill_json(total=from_image)])
    result = extract(image_document, BILL_PACK, provider, accept_from_image=frozenset({"total"}))
    assert "total" in result.review
    assert result.errors[-1].startswith("total: fails rule amounts_add_up")


def test_a_rule_naming_a_field_the_schema_lacks_fails_when_the_pack_is_built() -> None:
    typo = Rule[Bill](name="typo", description="d", fields=("subtotal",), holds=_adds_up)
    with pytest.raises(ValueError, match="rule typo names fields not in the schema: subtotal"):
        Pack(name="bill", schema=Bill, instructions="", printed=frozenset(), rules=(typo,))


def test_two_rules_with_one_name_fail_when_the_pack_is_built() -> None:
    with pytest.raises(ValueError, match="rule amounts_add_up is declared twice"):
        Pack(
            name="bill",
            schema=Bill,
            instructions="",
            printed=frozenset(),
            rules=(ADDS_UP, ADDS_UP),
        )
