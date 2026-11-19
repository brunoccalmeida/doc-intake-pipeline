"""Extract one receipt with the configured real provider. Costs money: run on purpose.

    uv run poe extract path/to/receipt.pdf

Prints the validated result as JSON on stdout (it holds document content, so
it is never logged). On stderr, one run-log line (``core.runlog``): status,
errors, calls, retries, tokens, latency and cost, with no content.

The document is logged by the SHA-256 of its bytes, never by its file name,
which can be a client's: whoever has the file finds its line by hashing it.

Configuration is checked before the file is read (fail fast): an unpriced
model or a missing key stops the run before anything is paid for.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from core.config import Settings
from core.ingest import IngestError, OcrDataMissingError, ingest
from core.pricing import price_of
from core.runlog import extract_logged, log_unreadable, new_run_id
from packs.receipt import RECEIPT
from providers import make_provider
from scripts.logs import configure_run_log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("path", type=Path, help="PDF, PNG or JPEG of one receipt")
    args = parser.parse_args(argv)
    path: Path = args.path

    settings = Settings()
    configure_run_log(settings.log_level)
    price_of(settings.model)
    provider = make_provider(settings)
    run_id = new_run_id()

    try:
        content = path.read_bytes()
    except OSError as error:
        print(f"ERROR: cannot read {path}: {error.strerror}", file=sys.stderr)
        return 1
    document_id = hashlib.sha256(content).hexdigest()

    try:
        document = ingest(path, tessdata_dir=settings.tessdata_dir)
    except OcrDataMissingError:
        raise
    except IngestError as error:
        log_unreadable(
            error,
            pack_name=RECEIPT.name,
            document_id=document_id,
            run_id=run_id,
            provider_name=settings.provider,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    result, _ = extract_logged(
        document,
        RECEIPT,
        provider,
        document_id=document_id,
        run_id=run_id,
        provider_name=settings.provider,
        max_retries=settings.max_retries,
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
