"""FATURA (CC BY 4.0) annotations converted to invoice golden records (#69).

FATURA annotates each object with its printed text, label included
(``"TOTAL : 870.74 USD"``), so the golden value is parsed from that text and
the whole text is the citation, read from the image as the annotators did.
Anything the converter does not recognize raises ``FaturaError`` (fail fast):
a golden record built from a guess would score the pipeline against a wrong
answer. The rules match the invoice pack's instructions; what FATURA leaves out
or gets wrong is in ``docs/DATA.md``.

The golden set is two instances of each template that FATURA's second split
holds out (``Strat2_Split.txt``), so the prompt is never tuned on a layout it
is scored on.
"""

import ast
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from doc_intake.core.result import Citation, ExtractedField
from doc_intake.packs.invoice import Invoice

GOLDEN_DIR = Path(__file__).parent / "golden" / "fatura"
INSTANCES = (0, 1)

NOT_PRINTED = "not printed"
PER_RATE_ONLY = "tax printed only per rate, with no total"
DOLLAR_ONLY = "only '$' printed, which several currencies use"
NO_CURRENCY = "no currency printed"

_NUMBER_LABELS = ("INVOICE #", "INVOICE ID", "Invoice number")
_DATE = re.compile(r"\b\d{2}-[A-Z][a-z]{2}-\d{4}\b")
# The amount closes the text, optionally followed by the only symbols FATURA prints.
_AMOUNT = re.compile(r"(?P<amount>\d+\.\d+)\s*(?P<symbol>USD|EUR|\$)?\s*$")
_CODES = {"USD": "USD", "EUR": "EUR"}
_GST = re.compile(r"^GST\(\d+(?:\.\d+)?%\)$")


class FaturaError(ValueError):
    """An annotation the converter cannot read without guessing."""


def parse_number(text: str) -> str:
    for label in _NUMBER_LABELS:
        if text.startswith(label):
            return text.removeprefix(label).strip()
    raise FaturaError(f"no known label in {text!r}")


def parse_date(text: str) -> date:
    found = _DATE.findall(text)
    if len(found) != 1:
        raise FaturaError(f"expected one DD-Mon-YYYY date in {text!r}")
    return datetime.strptime(found[0], "%d-%b-%Y").date()


def parse_amount(text: str) -> tuple[Decimal, str | None]:
    match = _AMOUNT.search(text)
    if match is None:
        raise FaturaError(f"no amount at the end of {text!r}")
    return Decimal(match["amount"]), match["symbol"]


def _label_dropped(text: str, label: str) -> str:
    if not text.startswith(label):
        raise FaturaError(f"expected {label!r} at the start of {text!r}")
    return " ".join(text.removeprefix(label).split())


def _cited[T](value: T, quote: str) -> ExtractedField[T]:
    return ExtractedField[T](
        value=value, citation=Citation(page=1, source="image", quote=quote), reason=None
    )


def _amount(text: str) -> Decimal:
    return parse_amount(text)[0]


def _seller_name(text: str) -> str:
    return " ".join(text.split())


def _seller_address(text: str) -> str:
    return _label_dropped(text, "Address:")


def to_invoice(annotation: Mapping[str, object]) -> Invoice:
    """The golden invoice of one ``Original_Format`` annotation."""
    texts = _texts(annotation)

    def field[T](name: str, parse: Callable[[str], T]) -> ExtractedField[T]:
        text = texts.get(name)
        if text is None:
            return ExtractedField[T](value=None, citation=None, reason=NOT_PRINTED)
        return _cited(parse(text), text)

    if "AMOUNT_DUE" in texts and "TOTAL" not in texts:
        raise FaturaError("AMOUNT_DUE without TOTAL: no golden template decides which is the total")
    return Invoice(
        number=field("NUMBER", parse_number),
        date=field("DATE", parse_date),
        due_date=field("DUE_DATE", parse_date),
        seller_name=field("SELLER_NAME", _seller_name),
        seller_address=field("SELLER_ADDRESS", _seller_address),
        subtotal=field("SUB_TOTAL", _amount),
        tax=_tax(texts),
        total=field("TOTAL", _amount),
        currency=_currency(texts),
    )


def _texts(annotation: Mapping[str, object]) -> dict[str, str]:
    """Each annotated object's text; ``OTHER`` is stale template text, not the page."""
    texts: dict[str, str] = {}
    for name, entry in annotation.items():
        if name == "OTHER" or not isinstance(entry, Mapping):
            continue
        text = cast("Mapping[str, object]", entry).get("text")
        if isinstance(text, str):
            texts[name] = text
    return texts


def _tax(texts: Mapping[str, str]) -> ExtractedField[Decimal]:
    gst = sorted(name for name in texts if _GST.match(name))
    if "TAX" in texts:
        return _cited(_amount(texts["TAX"]), texts["TAX"])
    if len(gst) == 1:
        return _cited(_amount(texts[gst[0]]), texts[gst[0]])
    reason = PER_RATE_ONLY if gst else NOT_PRINTED
    return ExtractedField[Decimal](value=None, citation=None, reason=reason)


def _currency(texts: Mapping[str, str]) -> ExtractedField[str]:
    # The total's line first: it is the line a reader takes the currency from.
    lines = [texts[name] for name in ("TOTAL", "SUB_TOTAL", "TAX") if name in texts]
    printed = [(symbol, line) for line in lines if (symbol := parse_amount(line)[1]) is not None]
    symbols = {symbol for symbol, _ in printed}
    if len(symbols) > 1:
        raise FaturaError(f"currencies disagree: {sorted(symbols)}")
    if not printed:
        return ExtractedField[str](value=None, citation=None, reason=NO_CURRENCY)
    symbol, line = printed[0]
    if symbol == "$":
        return ExtractedField[str](value=None, citation=None, reason=DOLLAR_ONLY)
    return _cited(_CODES[symbol], line)


def held_out_templates(split: str) -> list[int]:
    """``test_inds`` of ``Strat2_Split.txt``, following its alias to ``dev_inds``."""
    names: dict[str, object] = {}
    for statement in ast.parse(split).body:
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1):
            raise FaturaError("Strat2_Split.txt holds more than single assignments")
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            raise FaturaError("Strat2_Split.txt assigns to something other than a name")
        value = statement.value
        names[target.id] = (
            names[value.id] if isinstance(value, ast.Name) else ast.literal_eval(value)
        )
    held_out = names.get("test_inds")
    if not isinstance(held_out, list):
        raise FaturaError("Strat2_Split.txt has no test_inds list")
    templates: list[int] = []
    for number in cast("list[object]", held_out):
        if not isinstance(number, int):
            raise FaturaError(f"test_inds holds {number!r}, not a template number")
        templates.append(number)
    return templates


def golden_ids(templates: Iterable[int]) -> list[str]:
    return [f"Template{t}_Instance{i}" for t in templates for i in INSTANCES]
