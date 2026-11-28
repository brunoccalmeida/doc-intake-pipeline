"""FATURA annotations converted to invoice golden records (#69, docs/DATA.md).

FATURA annotates each object with its printed text, label included
(``"TOTAL : 870.74 USD"``), so the golden value is parsed from that text and
the text itself is the citation. Anything the converter does not recognize
stops it: a golden record built from a guess would score the pipeline
against a wrong answer.
"""

import hashlib
import json
import re
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from doc_intake.packs.invoice import Invoice
from evals.fatura import (
    GOLDEN_DIR,
    FaturaError,
    golden_ids,
    held_out_templates,
    parse_amount,
    parse_date,
    parse_number,
    to_invoice,
)
from scripts.build_fatura_golden import build


def box(text: str) -> dict[str, Any]:
    return {"bbox": [[0.0, 0.0], [1.0, 1.0]], "text": text}


def annotation(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "TABLE": [[{"bbox": [[0.0, 0.0], [1.0, 1.0]]}]],
        "OTHER": {"text": "stale template text, not the page"},
        "NUMBER": box("INVOICE # INV/78-64/532"),
        "DATE": box("Invoice Date: 14-Apr-2022"),
        "DUE_DATE": box("Due Date : 19-Mar-2002"),
        "SELLER_NAME": box("Berg, Ward and Wright"),
        "SELLER_ADDRESS": box("Address:5776 Whitney Meadow\nWest Adriennebury, ID 40049 US"),
        "SUB_TOTAL": box("SUB_TOTAL : 885.25  USD"),
        "TAX": box("TAX:VAT (3.22%):  28.51 USD"),
        "TOTAL": box("TOTAL : 870.74 USD"),
    }
    fields.update(overrides)
    return {name: value for name, value in fields.items() if value is not None}


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("INVOICE # INV/78-64/532", "INV/78-64/532"),
        ("INVOICE ID 5Y3M7d-590", "5Y3M7d-590"),
        ("Invoice number 2970-559", "2970-559"),
    ],
)
def test_number_drops_its_label(text: str, number: str) -> None:
    assert parse_number(text) == number


def test_unknown_number_label_stops_the_conversion() -> None:
    with pytest.raises(FaturaError, match=re.escape("no known label in 'Bill No. 12'")):
        parse_number("Bill No. 12")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Invoice Date: 14-Apr-2022", date(2022, 4, 14)),
        ("Date: 08-Jan-1999", date(1999, 1, 8)),
        ("Due Date : 31-Jul-2019", date(2019, 7, 31)),
    ],
)
def test_date_is_read_day_month_year(text: str, expected: date) -> None:
    assert parse_date(text) == expected


def test_text_without_one_date_stops_the_conversion() -> None:
    with pytest.raises(FaturaError, match="one DD-Mon-YYYY date"):
        parse_date("Date: 2022/04/14")


@pytest.mark.parametrize(
    ("text", "amount", "symbol"),
    [
        ("TOTAL : 870.74 USD", Decimal("870.74"), "USD"),
        ("SUB_TOTAL : 645.92  $", Decimal("645.92"), "$"),
        ("TAX:VAT (3.22%):  28.51 EUR", Decimal("28.51"), "EUR"),
        ("GST(7%) : 45.21", Decimal("45.21"), None),
        ("BALANCE DUE : 1262.37 USD", Decimal("1262.37"), "USD"),
    ],
)
def test_amount_is_the_last_number_and_its_symbol(
    text: str, amount: Decimal, symbol: str | None
) -> None:
    assert parse_amount(text) == (amount, symbol)


def test_unknown_currency_symbol_stops_the_conversion() -> None:
    with pytest.raises(FaturaError, match=re.escape("no amount at the end of 'TOTAL : 10.00 GBP'")):
        parse_amount("TOTAL : 10.00 GBP")


def test_annotation_becomes_a_cited_invoice() -> None:
    invoice = to_invoice(annotation())
    assert invoice.number.value == "INV/78-64/532"
    assert invoice.date.value == date(2022, 4, 14)
    # Copied as printed, even when it precedes the issue date (a generator artifact).
    assert invoice.due_date.value == date(2002, 3, 19)
    assert invoice.seller_name.value == "Berg, Ward and Wright"
    assert invoice.seller_address.value == "5776 Whitney Meadow West Adriennebury, ID 40049 US"
    # As printed, though 885.25 + 28.51 is not 870.74: FATURA's amounts do not add up.
    assert invoice.subtotal.value == Decimal("885.25")
    assert invoice.tax.value == Decimal("28.51")
    assert invoice.total.value == Decimal("870.74")
    assert invoice.currency.value == "USD"
    citation = invoice.total.citation
    assert citation is not None
    assert (citation.page, citation.source, citation.quote) == (1, "image", "TOTAL : 870.74 USD")


def test_field_not_annotated_is_empty_with_a_reason() -> None:
    invoice = to_invoice(annotation(TOTAL=None, NUMBER=None))
    assert invoice.total.value is None
    assert invoice.total.reason == "not printed"
    assert invoice.number.value is None


def test_single_gst_line_is_the_tax() -> None:
    invoice = to_invoice(annotation(TAX=None, **{"GST(7%)": box("GST(7%) : 45.21")}))
    assert invoice.tax.value == Decimal("45.21")


def test_tax_printed_only_per_rate_is_empty() -> None:
    rates = {"GST(5%)": box("GST(5%) : 23.16"), "GST(12%)": box("GST(12%) : 55.58")}
    invoice = to_invoice(annotation(TAX=None, **rates))
    assert invoice.tax.value is None
    assert invoice.tax.reason == "tax printed only per rate, with no total"


def test_dollar_sign_alone_leaves_the_currency_empty() -> None:
    invoice = to_invoice(
        annotation(
            SUB_TOTAL=box("SUB_TOTAL : 645.92  $"),
            TAX=box("TAX:VAT (3.00%):  14.52 $"),
            TOTAL=box("TOTAL : 653.95 $"),
        )
    )
    assert invoice.currency.value is None
    assert invoice.currency.reason == "only '$' printed, which several currencies use"


def test_currency_cites_the_total_line() -> None:
    invoice = to_invoice(annotation())
    assert invoice.currency.citation is not None
    assert invoice.currency.citation.quote == "TOTAL : 870.74 USD"


def test_mixed_currencies_stop_the_conversion() -> None:
    with pytest.raises(FaturaError, match="currencies disagree"):
        to_invoice(annotation(SUB_TOTAL=box("SUB_TOTAL : 885.25  EUR")))


def test_amount_due_without_total_stops_the_conversion() -> None:
    # Not in the golden templates; deciding it unseen would be a guess.
    with pytest.raises(FaturaError, match="AMOUNT_DUE"):
        to_invoice(annotation(TOTAL=None, AMOUNT_DUE=box("AMOUNT_DUE : 1141.74 USD")))


def test_held_out_templates_follow_test_inds_through_its_alias() -> None:
    split = "train_inds = [3, 11]\ndev_inds = [50, 7, 32]\ntest_inds = dev_inds\n"
    assert held_out_templates(split) == [50, 7, 32]


def test_golden_ids_are_two_instances_per_held_out_template() -> None:
    assert golden_ids([50, 7]) == [
        "Template50_Instance0",
        "Template50_Instance1",
        "Template7_Instance0",
        "Template7_Instance1",
    ]


def _fake_zip(path: Path) -> str:
    root = "invoices_dataset_final/"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(root + "Strat2_Split.txt", "dev_inds = [9]\ntest_inds = dev_inds\n")
        for instance in (0, 1):
            name = f"Template9_Instance{instance}"
            archive.writestr(f"{root}images/{name}.jpg", b"jpeg bytes " + bytes([instance]))
            archive.writestr(
                f"{root}Annotations/Original_Format/{name}.json", json.dumps(annotation())
            )
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def test_build_writes_each_image_and_golden_record(tmp_path: Path) -> None:
    archive = tmp_path / "FATURA2.zip"
    md5 = _fake_zip(archive)
    written = build(archive, tmp_path / "golden", md5=md5)
    assert written == ["Template9_Instance0", "Template9_Instance1"]
    image = (tmp_path / "golden" / "Template9_Instance1.jpg").read_bytes()
    assert image == b"jpeg bytes \x01"
    golden = (tmp_path / "golden" / "Template9_Instance0.json").read_text(encoding="utf-8")
    assert Invoice.model_validate_json(golden).total.value == Decimal("870.74")


def test_build_refuses_an_archive_with_another_checksum(tmp_path: Path) -> None:
    archive = tmp_path / "FATURA2.zip"
    _fake_zip(archive)
    with pytest.raises(FaturaError, match="MD5"):
        build(archive, tmp_path / "golden", md5="0" * 32)
    assert not (tmp_path / "golden").exists()


def test_committed_golden_set_is_the_selection_and_valid() -> None:
    images = sorted(path.stem for path in GOLDEN_DIR.glob("*.jpg"))
    records = sorted(path.stem for path in GOLDEN_DIR.glob("*.json"))
    assert len(images) == 20
    assert images == records
    for name in records:
        Invoice.model_validate_json((GOLDEN_DIR / f"{name}.json").read_bytes())


def test_committed_golden_set_holds_out_the_split_templates() -> None:
    # Strat2_Split.txt's test_inds (= dev_inds) in FATURA2.zip, MD5-pinned.
    held_out = [50, 7, 32, 39, 2, 12, 4, 49, 10, 25]
    names = sorted(path.stem for path in GOLDEN_DIR.glob("*.json"))
    assert names == sorted(golden_ids(held_out))


def test_committed_golden_records_are_canonical_json() -> None:
    # Written by the converter, not by hand: the bytes are exactly the model's dump.
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert Invoice.model_validate_json(text).model_dump_json(indent=2) + "\n" == text


@pytest.mark.parametrize(
    "text", ["TOTAL : 1,262.37 USD", "TOTAL : -12.37 USD", "TOTAL : 12.37.5 USD"]
)
def test_an_amount_not_read_whole_stops_the_conversion(text: str) -> None:
    # A search for the last number would read 262.37 from 1,262.37: a wrong golden value.
    with pytest.raises(FaturaError, match="no amount at the end of"):
        parse_amount(text)


def test_an_annotated_object_without_text_stops_the_conversion() -> None:
    # Only TABLE (boxes) and OTHER (stale template text) are expected without page text.
    with pytest.raises(FaturaError, match="TOTAL has no text"):
        to_invoice(annotation(TOTAL={"bbox": [[0.0, 0.0], [1.0, 1.0]]}))
