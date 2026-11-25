"""SROIE golden set: selection rule, normalization and conversion to the schema.

Pure functions over committed data, so no download and no network: the
fetched files are checked separately (``test_golden_sroie.py``).
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from doc_intake.core.result import Citation, ExtractedField
from evals.sroie import (
    MANIFEST_PATH,
    TEST_IDS_PATH,
    Amounts,
    load_amounts,
    load_manifest,
    parse_date,
    parse_total,
    select,
    to_receipt,
)

IDS = [f"X5100000000{n}" for n in range(10)]
NOT_PRINTED = ExtractedField[Decimal](value=None, citation=None, reason="not printed")
NO_AMOUNTS = Amounts(net=NOT_PRINTED, tax=NOT_PRINTED, rounding=NOT_PRINTED)


def test_selection_is_independent_of_input_order() -> None:
    assert select(IDS, seed="s", size=4) == select(list(reversed(IDS)), seed="s", size=4)


def test_selection_depends_on_the_seed() -> None:
    assert select(IDS, seed="a", size=4) != select(IDS, seed="b", size=4)


def test_selection_is_pinned_to_sha256() -> None:
    # Known answer: a change to the ranking (another hash, another key format)
    # would silently pick another golden set, so it must fail here.
    # Computed apart from the code: sorted(ids, key=sha256(f"s:{id}"))[:3], sorted.
    assert select(IDS, seed="s", size=3) == ["X51000000002", "X51000000003", "X51000000007"]


def test_committed_manifest_is_the_output_of_the_selection_rule() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    split = TEST_IDS_PATH.read_text(encoding="utf-8").split()

    assert len(split) == 347
    assert [entry.id for entry in manifest.receipts] == select(
        split, seed=manifest.seed, size=manifest.size
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("07 MAR 2018", date(2018, 3, 7)),
        ("06 Feb 2017", date(2017, 2, 6)),
        ("08/03/18", date(2018, 3, 8)),
        ("09/03/2018", date(2018, 3, 9)),
        ("23-03-18", date(2018, 3, 23)),
        ("06-03-2018", date(2018, 3, 6)),
        # Day first, as printed in Malaysia: 7 June, not July 6.
        ("7/6/2016", date(2016, 6, 7)),
    ],
)
def test_date_is_read_day_first(text: str, expected: date) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["2018-03-07", "31/02/2018", "07 XYZ 2018", "", "07/03"])
def test_unknown_or_impossible_date_fails(text: str) -> None:
    with pytest.raises(ValueError, match="date"):
        parse_date(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("81.00", Decimal("81.00")), ("$8.20", Decimal("8.20")), ("RM 96.90", Decimal("96.90"))],
)
def test_total_keeps_exact_digits(text: str, expected: Decimal) -> None:
    total = parse_total(text)

    assert total == expected
    assert str(total) == str(expected)


@pytest.mark.parametrize("text", ["", "RM", "8,20", "1,234.00", "8.2"])
def test_unknown_total_format_fails(text: str) -> None:
    with pytest.raises(ValueError, match="total"):
        parse_total(text)


MYR = ExtractedField[str](
    value="MYR", citation=Citation(page=1, source="image", quote="RM"), reason=None
)


def test_entities_become_a_receipt_citing_the_printed_text() -> None:
    entities = json.dumps(
        {
            "company": "SECURITY & OA TRADING",
            "date": "7/6/2016",
            "address": "LOT TC007 & 008, 3RD FLOOR, SG. WANG PLAZA",
            "total": "RM 399.00",
        }
    ).encode()

    receipt = to_receipt(entities, currency=MYR, amounts=NO_AMOUNTS)

    assert receipt.date.value == date(2016, 6, 7)
    assert receipt.date.citation == Citation(page=1, source="image", quote="7/6/2016")
    assert receipt.total.value == Decimal("399.00")
    assert receipt.total.citation == Citation(page=1, source="image", quote="RM 399.00")
    assert receipt.company.value == "SECURITY & OA TRADING"
    assert receipt.currency == MYR
    assert (receipt.net, receipt.tax, receipt.rounding) == (
        NO_AMOUNTS.net,
        NO_AMOUNTS.tax,
        NO_AMOUNTS.rounding,
    )


def test_amounts_load_by_receipt_id(tmp_path: Path) -> None:
    path = tmp_path / "sroie-amounts.json"
    path.write_text(json.dumps({"X51005447841": NO_AMOUNTS.model_dump(mode="json")}), "utf-8")

    assert load_amounts(path) == {"X51005447841": NO_AMOUNTS}


def test_missing_amounts_file_says_where_it_comes_from(tmp_path: Path) -> None:
    # The annotation quotes the receipts, so it lives in the private clone (docs/DATA.md).
    with pytest.raises(FileNotFoundError, match="private recordings repository"):
        load_amounts(tmp_path / "sroie-amounts.json")


@pytest.mark.parametrize("missing", ["company", "date", "address", "total"])
def test_entities_missing_a_field_fail(missing: str) -> None:
    fields = {"company": "C", "date": "09/03/2018", "address": "A", "total": "1.00"}
    del fields[missing]

    with pytest.raises(ValueError, match=missing):
        to_receipt(json.dumps(fields).encode(), currency=MYR, amounts=NO_AMOUNTS)
