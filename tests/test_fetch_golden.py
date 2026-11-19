"""The golden set is fetched pinned and verified, then converted locally.

The download is replaced by a fake, so these tests never touch the network.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from core.result import ExtractedField
from evals.sroie import GoldenEntry, Manifest
from packs.receipt import Receipt
from scripts.download import ChecksumMismatchError
from scripts.fetch_golden import install

IMAGE = b"pretend jpeg"
ENTITIES = json.dumps(
    {"company": "C SDN BHD", "date": "09/03/2018", "address": "NO 1, JALAN", "total": "10.40"}
).encode()
RID = "X51005447841"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(*, image_sha256: str = sha(IMAGE), entities_sha256: str = sha(ENTITIES)) -> Manifest:
    entry = GoldenEntry(
        id=RID,
        image_sha256=image_sha256,
        entities_sha256=entities_sha256,
        currency=ExtractedField[str](value=None, citation=None, reason="no currency printed"),
    )
    return Manifest(source="o/r", commit="c" * 40, split="test", seed="s", size=1, receipts=[entry])


def serve(calls: list[str]) -> Callable[[str], bytes]:
    """A fake download that serves by file extension and records each URL."""

    def download(url: str) -> bytes:
        calls.append(url)
        return IMAGE if url.endswith(".jpg") else ENTITIES

    return download


def test_verified_files_and_the_converted_golden_record_are_written(tmp_path: Path) -> None:
    calls: list[str] = []

    install(tmp_path, manifest(), download=serve(calls))

    assert calls == [
        f"https://raw.githubusercontent.com/o/r/{'c' * 40}/test/img/{RID}.jpg",
        f"https://raw.githubusercontent.com/o/r/{'c' * 40}/test/entities/{RID}.txt",
    ]
    assert (tmp_path / f"{RID}.jpg").read_bytes() == IMAGE
    golden = Receipt.model_validate_json((tmp_path / f"{RID}.json").read_text(encoding="utf-8"))
    assert golden.total.citation is not None
    assert golden.total.citation.quote == "10.40"


def test_tampered_download_is_rejected_and_not_written(tmp_path: Path) -> None:
    with pytest.raises(ChecksumMismatchError, match=RID):
        install(tmp_path, manifest(image_sha256=sha(b"other")), download=serve([]))

    assert list(tmp_path.iterdir()) == []


def test_tampered_ground_truth_leaves_no_golden_record(tmp_path: Path) -> None:
    with pytest.raises(ChecksumMismatchError, match=f"{RID} ground truth"):
        install(tmp_path, manifest(entities_sha256=sha(b"other")), download=serve([]))

    # The image was verified before the failure, so keeping it is safe; the
    # unverified ground truth and any record converted from it are not written.
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"{RID}.jpg"]


def test_verified_files_are_not_downloaded_again(tmp_path: Path) -> None:
    install(tmp_path, manifest(), download=serve([]))
    calls: list[str] = []

    install(tmp_path, manifest(), download=serve(calls))

    assert calls == []
    assert (tmp_path / f"{RID}.json").is_file()
