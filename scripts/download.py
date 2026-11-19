"""Pinned downloads: HTTPS only, and bytes are trusted only after their SHA-256 matches.

Shared by the fetchers of pinned external data (OCR model, golden sets), so
the HTTPS check and the checksum rule live in one place.
"""

import hashlib
import urllib.request
from pathlib import Path


class ChecksumMismatchError(Exception):
    """The downloaded bytes are not the pinned ones."""


def download_https(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS URL: {url}")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - HTTPS checked above
        data: bytes = response.read()
    return data


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_verified(path: Path, sha256: str) -> bool:
    """True when ``path`` exists and holds exactly the pinned bytes."""
    return path.is_file() and sha256_hex(path.read_bytes()) == sha256


def write_atomically(path: Path, data: bytes) -> None:
    """Write through a temporary name, so an interrupted write leaves no usable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    partial.replace(path)
