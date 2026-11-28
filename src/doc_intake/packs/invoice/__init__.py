"""Invoice pack: the header and totals of a supplier invoice.

The fields are the ones FATURA annotates and every large vendor's prebuilt
invoice model returns (#69). Left out until a client needs them: the buyer
(FATURA prints two "bill to" blocks on some layouts, so even the golden set
cannot say which is the buyer), discounts, line items and a per-rate tax
breakdown. No sum rule: FATURA's generated amounts do not add up, so a rule
could not be proven on it (#69); the receipt pack carries one (D23).
"""

from pydantic import Field

from doc_intake.core.extract import Pack
from doc_intake.core.result import ExtractedField, IsoDate, StrictModel
from doc_intake.packs.values import CurrencyCode, Money


class Invoice(StrictModel, frozen=True):
    """Fields of one invoice. Every field is either a value cited from the
    document or null with the reason it is missing; never a guess."""

    number: ExtractedField[str] = Field(description="Invoice number as printed, without label.")
    date: ExtractedField[IsoDate] = Field(
        description="Issue date as YYYY-MM-DD; the quote keeps it as printed."
    )
    due_date: ExtractedField[IsoDate] = Field(
        description="Payment due date as YYYY-MM-DD; null when not printed."
    )
    seller_name: ExtractedField[str] = Field(description="Name of the seller as printed.")
    seller_address: ExtractedField[str] = Field(
        description="Address of the seller as printed, without label."
    )
    subtotal: ExtractedField[Money] = Field(
        description="Subtotal before tax, as a decimal number; null when not printed."
    )
    tax: ExtractedField[Money] = Field(
        description="All the tax as one printed amount; null when not printed as one amount."
    )
    total: ExtractedField[Money] = Field(
        description="Final amount payable, as a decimal number; null when not printed."
    )
    currency: ExtractedField[CurrencyCode] = Field(
        description="ISO 4217 code printed with the amounts; null for '$' alone or none."
    )


INVOICE = Pack(
    name="invoice",
    schema=Invoice,
    printed=frozenset({"number", "seller_name", "seller_address"}),
    instructions="""\
The document is a supplier invoice.
- number: the invoice number, without its label ("INVOICE #", "Invoice number"); \
not a purchase order, tax registration (GSTIN, VAT) or customer number.
- date and due_date: the issue date and the payment due date, converted to \
YYYY-MM-DD; each quote keeps the date as printed. Copy each date as printed, even \
when the due date is before the issue date. If the day and month order is \
ambiguous, prefer the order used by the country of the seller's address.
- seller_name and seller_address: the seller's (who issues the invoice and is \
paid), as printed, never the buyer's or the "bill to" party's; the address \
without its label ("Address:"), and without phone, e-mail or website.
- subtotal, tax and total: each one amount printed on the invoice, without the \
currency, never computed from other amounts and never corrected when they do \
not add up; null when the invoice does not print it. subtotal is the amount \
printed as the subtotal, before tax. tax is all the tax as one amount; when tax \
is printed only per rate, with no total tax line, tax is null. total is the \
final amount payable ("TOTAL", "BALANCE DUE", "AMOUNT DUE"). Each quote is the \
line that prints the amount.
- currency: the ISO 4217 code printed with the subtotal, tax or total (USD, EUR), \
or the code of a symbol used by one currency only (€ is EUR, £ is GBP); null when \
only "$" is printed, since several currencies use it, or when none is printed, \
even if the country suggests one.""",
)
