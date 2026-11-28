"""Build the committed invoice golden set from FATURA's archive (#69, docs/DATA.md).

    uv run poe build-fatura-golden <path to FATURA2.zip>

Download ``FATURA2.zip`` from https://zenodo.org/records/10371464 first (690 MB);
the build checks its MD5 against the record before reading anything, then
writes each selected image and its converted golden record to
``evals/golden/fatura``. The output is committed, so CI never downloads the
archive; rerun this only when the converter or the selection changes, and
commit the diff.
"""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from evals.fatura import GOLDEN_DIR, FaturaError, golden_ids, held_out_templates, to_invoice

# Published with the Zenodo record (files[0].checksum of records/10371464).
FATURA_MD5 = "4c9404462f22c5241eb1a290a02eb2a2"
_ROOT = "invoices_dataset_final/"


def build(archive_path: Path, target_dir: Path, *, md5: str = FATURA_MD5) -> list[str]:
    """Write ``<id>.jpg`` and ``<id>.json`` for every selected invoice; return the ids."""
    digest = hashlib.md5(usedforsecurity=False)
    with archive_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != md5:
        raise FaturaError(f"{archive_path} has MD5 {digest.hexdigest()}, expected {md5}")
    with zipfile.ZipFile(archive_path) as archive:
        split = archive.read(_ROOT + "Strat2_Split.txt").decode("utf-8")
        ids = golden_ids(held_out_templates(split))
        # Every record is converted before any file is written: no half-built set.
        records = {
            name: to_invoice(
                json.loads(archive.read(f"{_ROOT}Annotations/Original_Format/{name}.json"))
            )
            for name in ids
        }
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, invoice in records.items():
            (target_dir / f"{name}.jpg").write_bytes(archive.read(f"{_ROOT}images/{name}.jpg"))
            (target_dir / f"{name}.json").write_text(
                invoice.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
            )
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("archive", type=Path, help="FATURA2.zip from Zenodo")
    parser.add_argument("--target", type=Path, default=GOLDEN_DIR)
    args = parser.parse_args(argv)
    try:
        written = build(args.archive, args.target)
    except FaturaError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"wrote {len(written)} invoices to {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
