"""The fetched SROIE golden set: every record validates and every image is the pinned one.

Needs ``uv run poe fetch-golden`` first. Without it these tests fail, not skip:
a golden set that silently goes missing would let the eval pass on nothing.
"""

import hashlib
from pathlib import Path

import pytest

from doc_intake.core.config import Settings
from doc_intake.packs.receipt import AMOUNTS_ADD_UP, Receipt
from evals.sroie import MANIFEST_PATH, GoldenEntry, load_manifest

ENTRIES = load_manifest(MANIFEST_PATH).receipts


@pytest.fixture(scope="module")
def golden_dir() -> Path:
    path = Settings().sroie_dir
    if not path.is_dir():
        pytest.fail(f"no golden set in {path}: run 'uv run poe fetch-golden'")
    return path


def test_golden_set_has_twenty_receipts() -> None:
    assert len(ENTRIES) == 20
    assert len({entry.id for entry in ENTRIES}) == 20


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.id for entry in ENTRIES])
def test_golden_record_validates_and_image_is_pinned(golden_dir: Path, entry: GoldenEntry) -> None:
    record = Receipt.model_validate_json((golden_dir / f"{entry.id}.json").read_text("utf-8"))
    image = (golden_dir / f"{entry.id}.jpg").read_bytes()

    assert hashlib.sha256(image).hexdigest() == entry.image_sha256
    assert record.currency == entry.currency


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.id for entry in ENTRIES])
def test_annotated_amounts_add_up_to_the_sroie_total(golden_dir: Path, entry: GoldenEntry) -> None:
    # Our reading of net, tax and rounding (#66) is checked against SROIE's own
    # total wherever the rule applies: a misread amount fails here, not in the eval.
    record = Receipt.model_validate_json((golden_dir / f"{entry.id}.json").read_text("utf-8"))
    # A plain bool, so a failure prints the id, not the record: pytest would
    # show the call's arguments, and the CI log is public (D6).
    holds = AMOUNTS_ADD_UP.holds(record) is not False

    assert holds, f"{entry.id}: annotated amounts do not add up to the SROIE total"


def test_the_amounts_rule_applies_to_most_of_the_golden_set(golden_dir: Path) -> None:
    # Counted on #66: 14 of 20 print every amount; a change here is a changed annotation.
    records = [
        Receipt.model_validate_json((golden_dir / f"{entry.id}.json").read_text("utf-8"))
        for entry in ENTRIES
    ]
    applies = sum(AMOUNTS_ADD_UP.holds(record) is True for record in records)

    assert applies == 14
