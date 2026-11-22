"""Process an inbox folder in one run: a run folder out, with a CSV review queue.

A scheduler (``deploy/``) starts one run at a time; each run:

1. picks the documents ready in the inbox: a supported type, not hidden, and
   unmodified for ``settle`` (a folder synced by Google Drive or Dropbox may
   still be writing a file, and neither documents how it writes one);
2. creates its run folder, ``runs/<UTC time>/``, failing if it already exists,
   so two runs never mix and nothing is paid for before that check;
3. extracts every document, logging each by the hash of its bytes, never its
   file name (AGENTS.md invariant 6);
4. writes ``results.csv`` (one row per field) through a temporary file and
   ``os.replace``, so nobody opens half a file;
5. only then moves the originals to ``documents/`` beside it.

If a run stops before step 5, the files are still in the inbox and the next
run processes them again: a document may be paid for twice, never lost
(at-least-once). A provider error on one document (network, rate limit)
leaves that file in the inbox for the next run; a file that cannot be read
moves with the run as ``failed``, since reading it again cannot change.
"""

import csv
import hashlib
import io
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from doc_intake.core.extract import Pack
from doc_intake.core.ingest import (
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    IngestError,
    OcrDataMissingError,
    ingest,
)
from doc_intake.core.llm import LLMProvider
from doc_intake.core.result import ExtractionResult, is_field
from doc_intake.core.runlog import extract_logged, log_unreadable, new_run_id

SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES
RESULTS_NAME = "results.csv"
DOCUMENTS_NAME = "documents"

COLUMNS: tuple[str, ...] = (
    "file",
    "document_status",
    "field",
    "field_status",
    "value",
    "page",
    "source",
    "quote",
    "note",
)

# A cell starting with one of these may run as a formula in Excel or Sheets
# (OWASP, "CSV Injection"), full-width forms included. Values come from
# documents a third party wrote, so they are untrusted input.
_FORMULA_START = (
    "=",
    "+",
    "-",
    "@",
    "\t",
    "\r",
    "\n",
    "\N{FULLWIDTH EQUALS SIGN}",
    "\N{FULLWIDTH PLUS SIGN}",
    "\N{FULLWIDTH HYPHEN-MINUS}",
    "\N{FULLWIDTH COMMERCIAL AT}",
)
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def spreadsheet_safe(text: str) -> str:
    """``text`` as a cell that cannot start a formula: prefixed with ``'`` if needed.

    A plain number (``-12.50``) is kept, so it stays a number in the sheet: it
    has no function or reference to run. The ``'`` prefix is OWASP's
    recommendation; Excel shows it as text and hides the quote.
    """
    if text.startswith(_FORMULA_START) and not _PLAIN_NUMBER.fullmatch(text):
        return "'" + text
    return text


def ready_documents(inbox: Path, *, settle: timedelta, now: datetime) -> list[Path]:
    """The inbox files a run takes, in name order (see the module docstring, step 1)."""
    if not inbox.is_dir():
        raise FileNotFoundError(f"inbox folder not found: {inbox}")
    ready: list[Path] = []
    for path in sorted(inbox.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if now - modified >= settle:
            ready.append(path)
    return ready


@dataclass(frozen=True, slots=True)
class RunReport:
    """What a run did. ``folder`` is None when the inbox had nothing ready."""

    folder: Path | None
    documents: int
    needs_review: int
    failed: int


@dataclass(frozen=True, slots=True)
class _Outcome[S: BaseModel]:
    path: Path
    result: ExtractionResult[S]
    move: bool


def run_inbox[S: BaseModel](
    inbox: Path,
    runs: Path,
    pack: Pack[S],
    provider: LLMProvider,
    *,
    tessdata_dir: Path,
    provider_name: str,
    max_retries: int,
    settle: timedelta,
    now: datetime,
) -> RunReport:
    """Process the documents ready in ``inbox`` into a new folder under ``runs``.

    Raises ``OcrDataMissingError`` (configuration, not the document) before
    anything is written or moved, and ``FileExistsError`` if this run's folder
    already exists.
    """
    documents = ready_documents(inbox, settle=settle, now=now)
    if not documents:
        return RunReport(folder=None, documents=0, needs_review=0, failed=0)

    folder = runs / now.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    runs.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    try:
        run_id = new_run_id()
        outcomes = [
            _process(path, pack, provider, tessdata_dir, provider_name, max_retries, run_id)
            for path in documents
        ]
    except BaseException:
        folder.rmdir()  # still empty: nothing was written
        raise

    _write_csv(folder / RESULTS_NAME, outcomes)
    moved = folder / DOCUMENTS_NAME
    moved.mkdir()
    for outcome in outcomes:
        if outcome.move:
            shutil.move(outcome.path, moved / outcome.path.name)
    return RunReport(
        folder=folder,
        documents=len(outcomes),
        needs_review=sum(o.result.status == "needs_review" for o in outcomes),
        failed=sum(o.result.status == "failed" for o in outcomes),
    )


def _process[S: BaseModel](
    path: Path,
    pack: Pack[S],
    provider: LLMProvider,
    tessdata_dir: Path,
    provider_name: str,
    max_retries: int,
    run_id: str,
) -> _Outcome[S]:
    document_id = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        document = ingest(path, tessdata_dir=tessdata_dir)
    except OcrDataMissingError:
        raise
    except IngestError as error:
        log_unreadable(
            error,
            pack_name=pack.name,
            document_id=document_id,
            run_id=run_id,
            provider_name=provider_name,
        )
        failed = ExtractionResult[S](status="failed", errors=[str(error)])
        return _Outcome(path, failed, move=True)
    try:
        result, _ = extract_logged(
            document,
            pack,
            provider,
            document_id=document_id,
            run_id=run_id,
            provider_name=provider_name,
            max_retries=max_retries,
        )
    except Exception as error:
        # Logged by extract_logged with the calls already paid. Only the
        # class: the message of a provider error may quote the document.
        note = f"{type(error).__name__}; left in the inbox for the next run"
        return _Outcome(path, ExtractionResult[S](status="failed", errors=[note]), move=False)
    return _Outcome(path, result, move=True)


def _rows[S: BaseModel](outcome: _Outcome[S]) -> Iterator[dict[str, str]]:
    result = outcome.result
    base = {"file": outcome.path.name, "document_status": result.status}
    if result.fields is None:
        yield base | {"note": "; ".join(result.errors)}
        return
    problems = dict(error.split(": ", 1) for error in result.errors)
    for name in type(result.fields).model_fields:
        field = getattr(result.fields, name)
        if not is_field(field):
            continue
        citation = field.citation
        row = base | {
            "field": name,
            "field_status": "needs_review" if name in result.review else "accepted",
            "value": "" if field.value is None else str(field.value),
            "page": "" if citation is None else str(citation.page),
            "source": "" if citation is None else citation.source,
            "quote": "" if citation is None else citation.quote,
            "note": problems.get(name) or field.reason or "",
        }
        yield row


def _write_csv[S: BaseModel](path: Path, outcomes: list[_Outcome[S]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, restval="")
    writer.writeheader()
    for outcome in outcomes:
        for row in _rows(outcome):
            writer.writerow({key: spreadsheet_safe(value) for key, value in row.items()})
    temporary = path.with_name(f".{path.name}.tmp")
    # utf-8-sig writes the BOM Excel needs to open the file as UTF-8.
    temporary.write_text(buffer.getvalue(), encoding="utf-8-sig", newline="")
    temporary.replace(path)  # atomic on one filesystem (os.replace)
