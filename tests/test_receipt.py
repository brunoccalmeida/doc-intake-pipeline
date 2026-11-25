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

from doc_intake.core.extract import extract
from doc_intake.core.ingest import Document, PageText
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.core.result import ExtractionResult
from doc_intake.packs.receipt import RECEIPT, Receipt


def cited(value: object, quote: str) -> dict[str, Any]:
    return {
        "value": value,
        "citation": {"page": 1, "source": "text", "quote": quote},
        "reason": None,
    }


NOT_PRINTED = {"value": None, "citation": None, "reason": "not printed"}


def receipt_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "company": cited("BOOK TA .K (TAMAN DAYA) SDN BHD", "BOOK TA .K (TAMAN DAYA) SDN BHD"),
        "address": cited("NO.53 55,57 & 59, JALAN SAGU 18, TAMAN DAYA", "NO.53 55,57 & 59"),
        "date": cited("2018-12-25", "25/12/2018"),
        "total": cited("9.00", "TOTAL 9.00"),
        "currency": {
            "value": None,
            "citation": None,
            "reason": "no currency symbol or code printed",
        },
        "net": NOT_PRINTED,
        "tax": NOT_PRINTED,
        "rounding": NOT_PRINTED,
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
        Receipt.model_validate_json(
            receipt_json(total={"value": "9.00", "citation": None, "reason": None})
        )


def test_empty_value_without_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="an empty value requires a reason"):
        Receipt.model_validate_json(
            receipt_json(company={"value": None, "citation": None, "reason": None})
        )


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
    ("raw", "shown"),
    [
        # A JSON number has no trailing zeros to keep; Pydantic reads its short form.
        pytest.param("23.40", '"23.4"', id="json-number-short-form"),
        # A JSON string goes through the Decimal constructor, which keeps them.
        pytest.param('"23.40"', '"23.40"', id="json-string-as-written"),
    ],
)
def test_total_precision_is_not_normalized(raw: str, shown: str) -> None:
    # D15: the value is the exact amount; the printed form lives in the quote.
    placeholder = '"TOTAL_PLACEHOLDER"'
    text = receipt_json(total=cited("TOTAL_PLACEHOLDER", "TOTAL 23.40")).replace(placeholder, raw)
    receipt = Receipt.model_validate_json(text)
    assert receipt.total.value == Decimal("23.40")
    assert f'"value":{shown}' in receipt.model_dump_json()
    assert receipt.total.citation is not None
    assert receipt.total.citation.quote == "TOTAL 23.40"


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


def test_receipt_pack_accepts_a_currency_code_converted_from_the_printed_symbol() -> None:
    # "RM" is printed and the pack asks for "MYR": only company and address
    # are read as printed, so the code is not held to its quote (review of #26).
    text = "ACME SDN BHD\nNO. 12, JALAN MAJU\n25/12/2018\nTOTAL RM 9.00"
    document = Document(pages=(PageText(number=1, text=text, source="text_layer", image=None),))
    answer = json.dumps(
        {
            "company": cited("ACME SDN BHD", "ACME SDN BHD"),
            "address": cited("NO. 12, JALAN MAJU", "NO. 12, JALAN MAJU"),
            "date": cited("2018-12-25", "25/12/2018"),
            "total": cited("9.00", "TOTAL RM 9.00"),
            "currency": cited("MYR", "RM 9.00"),
            "net": NOT_PRINTED,
            "tax": NOT_PRINTED,
            "rounding": NOT_PRINTED,
        }
    )

    result = extract_with(document, answer)

    assert (result.status, result.errors) == ("ok", [])


def extract_with(document: Document, answer: str) -> ExtractionResult[Receipt]:
    class Scripted:
        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(text=answer, input_tokens=1, output_tokens=1, model="fake")

    return extract(document, RECEIPT, Scripted())


def test_rounding_may_be_negative_but_net_and_tax_may_not() -> None:
    receipt = Receipt.model_validate_json(receipt_json(rounding=cited("-0.02", "ROUNDING -0.02")))
    assert receipt.rounding.value == Decimal("-0.02")
    for field in ("net", "tax"):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            Receipt.model_validate_json(receipt_json(**{field: cited("-0.02", "-0.02")}))


# The amounts as SROIE receipts print them (#66): the total includes the tax,
# and a rounding adjustment, as printed on the golden receipts, closes the sum.
AMOUNTS_PAGE = (
    "ACME SDN BHD\nTotal (Excluding GST): 25.45\nGST Payable: 1.53\n"
    "Total (Inclusive of GST): 26.98\nRounding Adj: 0.02\nTOTAL: 27.00"
)
AMOUNTS_DOCUMENT = Document(
    pages=(PageText(number=1, text=AMOUNTS_PAGE, source="text_layer", image=None),)
)


def amounts_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "company": cited("ACME SDN BHD", "ACME SDN BHD"),
        "address": NOT_PRINTED,
        "date": NOT_PRINTED,
        "total": cited("27.00", "TOTAL: 27.00"),
        "currency": NOT_PRINTED,
        "net": cited("25.45", "Total (Excluding GST): 25.45"),
        "tax": cited("1.53", "GST Payable: 1.53"),
        "rounding": cited("0.02", "Rounding Adj: 0.02"),
    }
    fields.update(overrides)
    return json.dumps(fields)


def test_receipt_amounts_that_add_up_with_rounding_are_ok() -> None:
    # 25.45 + 1.53 + 0.02 = 27.00
    result = extract_with(AMOUNTS_DOCUMENT, amounts_json())
    assert (result.status, result.errors) == ("ok", [])


def test_receipt_amounts_that_do_not_add_up_go_to_review_naming_the_rule() -> None:
    # The total before rounding, taken for the total paid.
    total = cited("26.98", "Total (Inclusive of GST): 26.98")
    result = extract_with(AMOUNTS_DOCUMENT, amounts_json(total=total))
    assert result.review == ["total", "net", "tax", "rounding"]
    assert result.errors[0] == (
        "total: fails rule amounts_add_up: net + tax + rounding must equal total"
    )


def test_receipt_rounding_not_printed_counts_as_zero() -> None:
    total = cited("26.98", "Total (Inclusive of GST): 26.98")
    result = extract_with(AMOUNTS_DOCUMENT, amounts_json(total=total, rounding=NOT_PRINTED))
    assert (result.status, result.review) == ("ok", [])


@pytest.mark.parametrize("empty", ["net", "tax", "total"])
def test_receipt_rule_does_not_apply_without_one_of_its_amounts(empty: str) -> None:
    # A tax-inclusive receipt often prints no net amount: nothing to check, no review.
    total = cited("26.98", "Total (Inclusive of GST): 26.98")
    overrides: dict[str, object] = {"total": total, empty: NOT_PRINTED}
    result = extract_with(AMOUNTS_DOCUMENT, amounts_json(**overrides))
    assert (result.status, result.review) == ("ok", [])
