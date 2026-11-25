"""Receipt pack: the fields read from a purchase receipt or simple invoice.

The first four are the SROIE fields, so the golden set (#5) maps onto them
directly; ``currency`` is extra and may be empty. ``net``, ``tax`` and
``rounding`` exist for the rule that the amounts add up (#66, D23); line items
and a per-rate tax breakdown are out of scope until a client needs them.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

from doc_intake.core.extract import Pack, Rule
from doc_intake.core.result import ExtractedField, IsoDate, StrictModel

# Decimal, never float: money must keep its exact digits (project invariant 5).
# Pydantic's default already rejects NaN and infinities for Decimal.
type Money = Annotated[Decimal, Field(ge=0)]
# A rounding adjustment goes either way: RM 82.02 is paid as 82.00 (Bank Negara Malaysia).
type SignedMoney = Decimal
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
    net: ExtractedField[Money] = Field(
        description="Amount before tax, as a decimal number; null when not printed."
    )
    tax: ExtractedField[Money] = Field(
        description="Total tax amount, added or included in the total, as a decimal number; "
        "null when not printed."
    )
    rounding: ExtractedField[SignedMoney] = Field(
        description="Rounding adjustment to the total, negative when it lowers the total; "
        "null when not printed."
    )


def _amounts_add_up(receipt: Receipt) -> bool | None:
    """``net + tax + rounding == total``, exactly; ``None`` without net, tax or total.

    A rounding that is not printed counts as zero. Exact, with no tolerance:
    the rounding is extracted instead, so a misread digit cannot hide in it.
    """
    net, tax, total = receipt.net.value, receipt.tax.value, receipt.total.value
    if net is None or tax is None or total is None:
        return None
    return net + tax + (receipt.rounding.value or 0) == total


AMOUNTS_ADD_UP = Rule[Receipt](
    name="amounts_add_up",
    description="net + tax + rounding must equal total",
    fields=("total", "net", "tax", "rounding"),
    holds=_amounts_add_up,
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
when no currency is printed, even if the country suggests one.
- net, tax and rounding: amounts printed on the receipt, never computed from \
other amounts; null when the receipt does not print them. net is the amount \
before tax (e.g. "Total Excluding GST", or the amount column of a tax summary); \
tax is the total tax, whether added to the total or included in it; rounding is \
the rounding adjustment line, negative when it lowers the total. Each quote is \
the line that prints the amount.""",
    rules=(AMOUNTS_ADD_UP,),
)
