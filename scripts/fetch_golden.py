"""Fetch the SROIE golden set, pinned by commit and verified by SHA-256, and convert it.

SROIE has no published licence, so neither its images nor its ground truth
are in the repository (``docs/DATA.md``). This downloads each selected
receipt's image and ground truth from the pinned mirror commit, checks both
against the manifest, and writes ``<id>.jpg`` plus ``<id>.json`` (the golden
``Receipt``) into the configured ``DOC_INTAKE_SROIE_DIR``.

Usage: ``uv run poe fetch-golden`` (idempotent: verified files are kept).
"""

import sys
from collections.abc import Callable
from pathlib import Path

from doc_intake.core.config import Settings
from evals.sroie import MANIFEST_PATH, Manifest, load_manifest, to_receipt
from scripts.download import (
    ChecksumMismatchError,
    download_https,
    is_verified,
    sha256_hex,
    write_atomically,
)


def _fetch(
    path: Path, url: str, sha256: str, label: str, download: Callable[[str], bytes]
) -> bytes:
    """The verified bytes at ``path``, downloading them first when needed."""
    if is_verified(path, sha256):
        return path.read_bytes()
    data = download(url)
    actual = sha256_hex(data)
    if actual != sha256:
        raise ChecksumMismatchError(f"{label}: expected SHA-256 {sha256}, got {actual} ({url})")
    write_atomically(path, data)
    return data


def install(
    target_dir: Path,
    manifest: Manifest,
    *,
    download: Callable[[str], bytes] = download_https,
) -> list[Path]:
    """Put every verified receipt and its golden record in ``target_dir``."""
    base = f"https://raw.githubusercontent.com/{manifest.source}/{manifest.commit}/{manifest.split}"
    written: list[Path] = []
    for entry in manifest.receipts:
        _fetch(
            target_dir / f"{entry.id}.jpg",
            f"{base}/img/{entry.id}.jpg",
            entry.image_sha256,
            f"{entry.id} image",
            download,
        )
        entities = _fetch(
            target_dir / f"{entry.id}.entities.txt",
            f"{base}/entities/{entry.id}.txt",
            entry.entities_sha256,
            f"{entry.id} ground truth",
            download,
        )
        try:
            receipt = to_receipt(entities, currency=entry.currency)
        except ValueError as error:
            raise ValueError(f"{entry.id}: {error}") from error
        golden = target_dir / f"{entry.id}.json"
        write_atomically(golden, (receipt.model_dump_json(indent=2) + "\n").encode())
        written.append(golden)
    return written


def main() -> int:
    target = Settings().sroie_dir
    written = install(target, load_manifest(MANIFEST_PATH))
    print(f"verified {len(written)} receipts in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
