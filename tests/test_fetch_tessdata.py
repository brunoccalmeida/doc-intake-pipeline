"""The OCR model is fetched pinned and verified: a changed file never reaches OCR.

The download is replaced by a fake, so these tests never touch the network.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.download import ChecksumMismatchError
from scripts.fetch_tessdata import install

PAYLOAD = b"pretend traineddata"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def serve(payload: bytes, calls: list[str]) -> Callable[[str], bytes]:
    """A fake download that records each URL asked for."""

    def download(url: str) -> bytes:
        calls.append(url)
        return payload

    return download


def test_verified_download_is_written(tmp_path: Path) -> None:
    calls: list[str] = []

    target = install(
        tmp_path / "tessdata", url="u", sha256=PAYLOAD_SHA256, download=serve(PAYLOAD, calls)
    )

    assert target == tmp_path / "tessdata" / "eng.traineddata"
    assert target.read_bytes() == PAYLOAD
    assert calls == ["u"]


def test_tampered_download_is_rejected_and_nothing_is_written(tmp_path: Path) -> None:
    with pytest.raises(ChecksumMismatchError, match=PAYLOAD_SHA256):
        install(tmp_path, url="u", sha256=PAYLOAD_SHA256, download=serve(b"evil", []))

    assert list(tmp_path.iterdir()) == []


def test_verified_file_already_present_is_not_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "eng.traineddata").write_bytes(PAYLOAD)
    calls: list[str] = []

    install(tmp_path, url="u", sha256=PAYLOAD_SHA256, download=serve(PAYLOAD, calls))

    assert calls == []


def test_stale_file_present_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "eng.traineddata").write_bytes(b"old model")
    calls: list[str] = []

    install(tmp_path, url="u", sha256=PAYLOAD_SHA256, download=serve(PAYLOAD, calls))

    assert (tmp_path / "eng.traineddata").read_bytes() == PAYLOAD
    assert calls == ["u"]
