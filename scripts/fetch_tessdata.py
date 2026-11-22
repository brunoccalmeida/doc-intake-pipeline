"""Install Tesseract's English model, pinned by commit and verified by SHA-256.

The tesserocr wheels bundle the Tesseract engine but not its language data
(tesserocr README, "tessdata"). This puts ``eng.traineddata`` from
``tesseract-ocr/tessdata_fast`` (Apache-2.0) into the configured
``DOC_INTAKE_TESSDATA_DIR``. ``tessdata_fast`` is the set the Tesseract docs
say most users want and Linux distributions ship ("Data Files").

The commit pins the URL and the checksum pins the bytes: a changed file fails
here instead of silently changing OCR output, and with it the eval. To update,
change both together.

Usage: ``uv run poe fetch-tessdata`` (idempotent: a verified file is kept).
"""

import sys
from collections.abc import Callable
from pathlib import Path

from doc_intake.core.config import Settings
from scripts.download import (
    ChecksumMismatchError,
    download_https,
    is_verified,
    sha256_hex,
    write_atomically,
)

COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
URL = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/eng.traineddata"
SHA256 = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
FILENAME = "eng.traineddata"


def install(
    target_dir: Path,
    *,
    url: str = URL,
    sha256: str = SHA256,
    download: Callable[[str], bytes] = download_https,
) -> Path:
    """Put the verified model in ``target_dir`` and return its path.

    The file is written only after the checksum matches, through a temporary
    name, so an interrupted or tampered download never leaves a usable file.
    """
    target = target_dir / FILENAME
    if is_verified(target, sha256):
        return target

    data = download(url)
    actual = sha256_hex(data)
    if actual != sha256:
        raise ChecksumMismatchError(f"{url}: expected SHA-256 {sha256}, got {actual}")

    write_atomically(target, data)
    return target


def main() -> int:
    target = install(Settings().tessdata_dir)
    print(f"verified {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
