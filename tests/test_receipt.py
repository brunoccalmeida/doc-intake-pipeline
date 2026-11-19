"""Receipt pack schema: the SROIE fields plus currency, as the LLM must return them.

Inputs are JSON text, as a provider returns them, so these tests exercise the
same parsing path as production (``model_validate_json``).
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from core.result import ExtractionResult
from packs.receipt import Receipt


def cited(value: object, quote: str) -> dict[str, Any]:
    return {"value": value, "citation": {"page": 1, "quote": quote}}


def receipt_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "company": cited("BOOK TA .K (TAMAN DAYA) SDN BHD", "BOOK TA .K (TAMAN DAYA) SDN BHD"),
        "address": cited("NO.53 55,57 & 59, JALAN SAGU 18, TAMAN DAYA", "NO.53 55,57 & 59"),
        "date": cited("2018-12-25", "25/12/2018"),
        "total": cited("9.00", "TOTAL 9.00"),
        "currency": {"value": None, "reason": "no currency symbol or code printed"},
    }
    fields.update(overrides)
    return json.dumps(fields)


def test_valid_receipt_is_accepted() -> None:
    receipt = Receipt.model_validate_json(receipt_json())
    assert receipt.company.value == "BOOK TA .K (TAMAN DAYA) SDN BHD"
    assert receipt.date.value == date(2018, 12, 25)
    assert receipt.total.value == Decimal("9.00")
    assert receipt.currency.value is None


def test_receipt_wrapped_in_a_result_is_accepted() -> None:
    raw = f'{{"status": "ok", "fields": {receipt_json()}}}'
    result = ExtractionResult[Receipt].model_validate_json(raw)
    assert result.fields is not None
    assert result.fields.total.value == Decimal("9.00")


def test_value_without_citation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="a value requires a citation"):
        Receipt.model_validate_json(receipt_json(total={"value": "9.00"}))


def test_empty_value_without_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="an empty value requires a reason"):
        Receipt.model_validate_json(receipt_json(company={"value": None}))


@pytest.mark.parametrize("field", ["company", "address"])
def test_blank_text_field_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="blank text is not a value"):
        Receipt.model_validate_json(receipt_json(**{field: cited("", "ACME")}))


def test_negative_total_is_rejected() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Receipt.model_validate_json(receipt_json(total=cited("-9.00", "TOTAL -9.00")))


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_total_is_rejected(raw: str) -> None:
    with pytest.raises(ValidationError, match="total"):
        Receipt.model_validate_json(receipt_json(total=cited(raw, "TOTAL")))


def test_decimal_text_keeps_its_exact_digits() -> None:
    receipt = Receipt.model_validate_json(receipt_json(total=cited("10.10", "10.10")))
    assert receipt.total.value is not None
    assert receipt.total.value.as_tuple() == Decimal("10.10").as_tuple()


def test_json_number_total_has_no_binary_rounding_error() -> None:
    # 10.10 has no exact binary form: Decimal(10.10) is 10.0999999999999996447...
    receipt = Receipt.model_validate_json(receipt_json(total=cited(10.10, "10.10")))
    assert receipt.total.value == Decimal("10.10")
    assert receipt.total.value != Decimal.from_float(10.10)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("25/12/2018", id="day-first-as-printed"),
        pytest.param("2018-12-25T00:00:00", id="datetime-not-date"),
        # Pydantic's lax mode, and even strict mode for text, read these as dates.
        pytest.param("1545696000", id="unix-timestamp-text"),
        pytest.param(1545696000, id="unix-timestamp-number"),
        pytest.param("20181225", id="iso-basic-format"),
    ],
)
def test_date_must_be_iso_calendar_date(raw: object) -> None:
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        Receipt.model_validate_json(receipt_json(date=cited(raw, "25/12/2018")))


@pytest.mark.parametrize("raw", ["RM", "myr", "MYRR", "$"])
def test_currency_must_be_an_iso_4217_code(raw: str) -> None:
    with pytest.raises(ValidationError, match="currency"):
        Receipt.model_validate_json(receipt_json(currency=cited(raw, "RM 9.00")))


def test_iso_4217_currency_is_accepted() -> None:
    receipt = Receipt.model_validate_json(receipt_json(currency=cited("MYR", "RM 9.00")))
    assert receipt.currency.value == "MYR"


def test_every_field_is_required() -> None:
    # Absent is not empty: an empty field must still be sent, with its reason.
    fields = json.loads(receipt_json())
    del fields["currency"]
    with pytest.raises(ValidationError, match="currency"):
        Receipt.model_validate(fields)
