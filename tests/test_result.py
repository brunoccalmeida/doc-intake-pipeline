"""Generic result types: every field is either cited or explained, never silently empty.

These rules are what invariant 1 ("nothing invented") looks like as code: the
schema itself refuses a value without evidence and an empty field without a
reason, so no caller can forget to check.
"""

import pytest
from pydantic import BaseModel, ValidationError

from core.result import Citation, ExtractedField, ExtractionResult


class Pair(BaseModel, frozen=True):
    """A minimal pack schema, so the generic result is tested without any real pack."""

    name: ExtractedField[str]


CITED = Citation(page=1, quote="ACME SDN BHD")


def test_value_with_citation_is_accepted() -> None:
    field = ExtractedField[str](value="ACME SDN BHD", citation=CITED)
    assert field.value == "ACME SDN BHD"
    assert field.citation == CITED


def test_empty_value_with_reason_is_accepted() -> None:
    field = ExtractedField[str](value=None, reason="no company name printed")
    assert field.value is None
    assert field.reason == "no company name printed"


def test_value_without_citation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="a value requires a citation"):
        ExtractedField[str](value="ACME SDN BHD")


def test_empty_value_without_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="an empty value requires a reason"):
        ExtractedField[str](value=None)


def test_value_with_reason_is_rejected() -> None:
    # A reason explains an absence; next to a value it would be an unread doubt.
    with pytest.raises(ValidationError, match="a reason only explains an empty value"):
        ExtractedField[str](value="ACME SDN BHD", citation=CITED, reason="blurry")


def test_empty_value_with_citation_is_rejected() -> None:
    # A citation is evidence for a value; with no value it cites nothing.
    with pytest.raises(ValidationError, match="a citation needs a value"):
        ExtractedField[str](value=None, citation=CITED, reason="illegible")


@pytest.mark.parametrize("quote", ["", "   "])
def test_blank_quote_is_rejected(quote: str) -> None:
    with pytest.raises(ValidationError, match="quote"):
        Citation(page=1, quote=quote)


def test_pages_are_numbered_from_one() -> None:
    with pytest.raises(ValidationError, match="page"):
        Citation(page=0, quote="ACME SDN BHD")


def test_unknown_keys_are_rejected() -> None:
    # An LLM that adds a key it was not asked for is not following the schema.
    with pytest.raises(ValidationError, match="confidence"):
        ExtractedField[str].model_validate(
            {"value": "x", "citation": {"page": 1, "quote": "x"}, "confidence": 0.9}
        )


def test_ok_result_carries_fields_and_no_errors() -> None:
    fields = Pair(name=ExtractedField[str](value="ACME SDN BHD", citation=CITED))
    result = ExtractionResult[Pair](status="ok", fields=fields)
    assert result.fields == fields
    assert result.errors == []


def test_failed_result_carries_errors_and_no_fields() -> None:
    result = ExtractionResult[Pair](status="failed", errors=["invalid JSON after 2 retries"])
    assert result.fields is None


def test_failed_result_without_errors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must say why"):
        ExtractionResult[Pair](status="failed")


def test_failed_result_with_fields_is_rejected() -> None:
    # A failure never ships partial fields: they would be read as valid.
    fields = Pair(name=ExtractedField[str](value="ACME SDN BHD", citation=CITED))
    with pytest.raises(ValidationError, match="failed result carries no fields"):
        ExtractionResult[Pair](status="failed", fields=fields, errors=["timeout"])


def test_needs_review_without_errors_is_rejected() -> None:
    fields = Pair(name=ExtractedField[str](value="ACME SDN BHD", citation=CITED))
    with pytest.raises(ValidationError, match="must say why"):
        ExtractionResult[Pair](status="needs_review", fields=fields)


def test_ok_result_without_fields_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires fields"):
        ExtractionResult[Pair](status="ok")


def test_ok_result_with_errors_is_rejected() -> None:
    fields = Pair(name=ExtractedField[str](value="ACME SDN BHD", citation=CITED))
    with pytest.raises(ValidationError, match="ok result carries no errors"):
        ExtractionResult[Pair](status="ok", fields=fields, errors=["quote not found"])


def test_results_are_immutable() -> None:
    # pyright already rejects this assignment statically; this test covers the
    # runtime layer, for code paths a type checker does not see (e.g. setattr).
    field = ExtractedField[str](value="ACME SDN BHD", citation=CITED)
    with pytest.raises(ValidationError, match="frozen"):
        field.value = "OTHER"  # pyright: ignore[reportAttributeAccessIssue]  # deliberate
