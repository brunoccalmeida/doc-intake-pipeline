"""Receipt pack: the fields read from a purchase receipt or simple invoice.

The first four are the SROIE fields, so the golden set (#5) maps onto them
directly; ``currency`` is extra and may be empty. Line items and tax breakdown
are out of scope until a client or the CORD set needs them.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

from doc_intake.core.extract import Pack
from doc_intake.core.result import ExtractedField, IsoDate, StrictModel

# Decimal, never float: money must keep its exact digits (project invariant 5).
# Pydantic's default already rejects NaN and infinities for Decimal.
type Money = Annotated[Decimal, Field(ge=0)]
type CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Receipt(StrictModel, frozen=True):
    """Fields of one receipt. Every field is either a value cited from the
    document or null with the reason it is missing; never a guess."""

    company: ExtractedField[str] = Field(description="Name of the seller as printed.")
    address: ExtractedField[str] = Field(description="Address of the seller as printed.")
    date: ExtractedField[IsoDate] = Field(
        description="Issue date as YYYY-MM-DD; the quote keeps it as printed."
    )
    total: ExtractedField[Money] = Field(
        description="Final amount paid, including tax, as a decimal number."
    )
    currency: ExtractedField[CurrencyCode] = Field(
        description="ISO 4217 code (e.g. MYR for 'RM'); null when not printed."
    )


RECEIPT = Pack(
    name="receipt",
    schema=Receipt,
    printed=frozenset({"company", "address"}),
    instructions="""\
The document is a purchase receipt or a simple invoice.
- company and address: the seller's, as printed (usually at the top), not the buyer's.
- date: the issue date, converted to YYYY-MM-DD; the quote keeps it as printed. \
If the day and month order is ambiguous, prefer the order used by the country of \
the address.
- total: the final amount paid, after tax and rounding, without the currency \
symbol; the quote is the line that shows it.
- currency: the ISO 4217 code of the printed symbol or code (RM is MYR); null \
when no currency is printed, even if the country suggests one.""",
)
