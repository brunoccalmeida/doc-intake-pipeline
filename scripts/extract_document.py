"""Extract one document with the configured provider: a paid call, unless replayed.

    uv run poe extract path/to/receipt.pdf
    uv run poe extract --pack invoice path/to/invoice.pdf  # default pack: receipt
    uv run poe extract --record DIR path/to/receipt.pdf  # paid once, answer stored in DIR
    uv run poe extract --replay DIR path/to/receipt.pdf  # the stored answer: no key, no cost

Prints the validated result as JSON on stdout (it holds document content, so
it is never logged). On stderr, one run-log line (``doc_intake.core.runlog``): status,
errors, calls, retries, tokens, latency and cost, with no content.

The document is logged by the SHA-256 of its bytes, never by its file name,
which can be a client's: whoever has the file finds its line by hashing it.

Configuration is checked before the file is read (fail fast): an unpriced
model or a missing key stops the run before anything is paid for.

``--record`` and ``--replay`` use the eval's recordings (``evals.recording``),
keyed by the request, provider and model: the demo (``demo/``) replays a
committed answer, so it renders without a key and shows a real model output.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from pydantic import BaseModel

from doc_intake.core.config import Settings
from doc_intake.core.extract import Pack
from doc_intake.core.ingest import Document, IngestError, OcrDataMissingError, ingest
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import price_of
from doc_intake.core.runlog import extract_logged, log_unreadable, new_run_id
from doc_intake.packs.invoice import INVOICE
from doc_intake.packs.receipt import RECEIPT
from doc_intake.providers import make_provider
from evals.recording import MissingRecordingError, RecordingProvider, RecordingStore, ReplayProvider
from scripts.logs import configure_run_log

DEFAULT_PACK = RECEIPT.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", type=Path, metavar="DIR", help="store the answer (paid)")
    mode.add_argument("--replay", type=Path, metavar="DIR", help="replay a stored answer")
    parser.add_argument("--pack", choices=(RECEIPT.name, INVOICE.name), default=DEFAULT_PACK)
    parser.add_argument("path", type=Path, help="PDF, PNG or JPEG of one document")
    args = parser.parse_args(argv)
    path: Path = args.path
    record: Path | None = args.record
    replay: Path | None = args.replay

    settings = Settings()
    configure_run_log(settings.log_level)
    price_of(settings.model)
    provider: LLMProvider
    if replay is not None:
        provider = ReplayProvider(
            RecordingStore(replay),
            provider=settings.provider,
            model=settings.model,
            record_command=f"uv run poe extract --record {replay} {path}",
        )
    elif record is not None:
        provider = RecordingProvider(
            make_provider(settings),
            RecordingStore(record),
            provider=settings.provider,
            model=settings.model,
        )
    else:
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
            pack_name=args.pack,
            document_id=document_id,
            run_id=run_id,
            provider_name=settings.provider,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    def run[S: BaseModel](pack: Pack[S], document: Document) -> int:
        try:
            result, _ = extract_logged(
                document,
                pack,
                provider,
                document_id=document_id,
                run_id=run_id,
                provider_name=settings.provider,
                max_retries=settings.max_retries,
            )
        except MissingRecordingError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(result.model_dump_json(indent=2))
        return 0 if result.status == "ok" else 1

    # One call per pack, not a lookup: each pack keeps its own schema type.
    match args.pack:
        case INVOICE.name:
            return run(INVOICE, document)
        case _:
            return run(RECEIPT, document)


if __name__ == "__main__":
    sys.exit(main())
