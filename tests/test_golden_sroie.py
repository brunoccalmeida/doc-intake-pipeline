"""The fetched SROIE golden set: every record validates and every image is the pinned one.

Needs ``uv run poe fetch-golden`` first. Without it these tests fail, not skip:
a golden set that silently goes missing would let the eval pass on nothing.
"""

import hashlib
from pathlib import Path

import pytest

from core.config import Settings
from evals.sroie import MANIFEST_PATH, GoldenEntry, load_manifest
from packs.receipt import Receipt

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
