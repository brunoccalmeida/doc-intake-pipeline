"""Invoice pack schema: the fields the LLM must return for an invoice.

Inputs are JSON text, as a provider returns them, so these tests exercise the
same parsing path as production (``model_validate_json``).
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from doc_intake.packs.invoice import INVOICE, Invoice


def cited(value: object, quote: str) -> dict[str, Any]:
    return {
        "value": value,
        "citation": {"page": 1, "source": "text", "quote": quote},
        "reason": None,
    }


def empty(reason: str) -> dict[str, Any]:
    return {"value": None, "citation": None, "reason": reason}


def invoice_json(**overrides: object) -> str:
    fields: dict[str, Any] = {
        "number": cited("INV/78-64/532", "INVOICE # INV/78-64/532"),
        "date": cited("2022-04-14", "Invoice Date: 14-Apr-2022"),
        "due_date": cited("2022-05-14", "Due Date : 14-May-2022"),
        "seller_name": cited("Example Supplies Ltd", "Example Supplies Ltd"),
        "seller_address": cited("1 Main Street Springfield", "Address:1 Main Street"),
        "subtotal": cited("885.25", "SUB_TOTAL : 885.25 USD"),
        "tax": empty("tax printed only per rate, with no total"),
        "total": cited("913.76", "TOTAL : 913.76 USD"),
        "currency": cited("USD", "TOTAL : 913.76 USD"),
    }
    fields.update(overrides)
    return json.dumps(fields)


def test_valid_invoice_is_accepted() -> None:
    invoice = Invoice.model_validate_json(invoice_json())
    assert invoice.number.value == "INV/78-64/532"
    assert invoice.date.value == date(2022, 4, 14)
    assert invoice.due_date.value == date(2022, 5, 14)
    assert invoice.total.value == Decimal("913.76")
    assert invoice.tax.value is None
    assert invoice.currency.value == "USD"


def test_the_fields_are_the_invoice_fields_in_order() -> None:
    # The order is the column order of the eval report and the batch output.
    assert list(Invoice.model_fields) == [
        "number",
        "date",
        "due_date",
        "seller_name",
        "seller_address",
        "subtotal",
        "tax",
        "total",
        "currency",
    ]


@pytest.mark.parametrize("field", ["subtotal", "tax", "total"])
def test_negative_amount_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Invoice.model_validate_json(invoice_json(**{field: cited("-1.00", "-1.00")}))


def test_currency_must_be_an_iso_code() -> None:
    # "$" is shared by many currencies: the instructions ask for null, not a guess.
    with pytest.raises(ValidationError, match="should match pattern"):
        Invoice.model_validate_json(invoice_json(currency=cited("$", "TOTAL : 913.76 $")))


def test_number_and_seller_are_read_as_printed() -> None:
    # Their value must sit inside the quote (D-printed fields); amounts and dates are normalized.
    assert frozenset({"number", "seller_name", "seller_address"}) == INVOICE.printed


def test_the_pack_has_no_sum_rule() -> None:
    # FATURA prints amounts that do not add up (#69): a sum rule could not be proven there.
    assert INVOICE.rules == ()
    assert INVOICE.name == "invoice"
