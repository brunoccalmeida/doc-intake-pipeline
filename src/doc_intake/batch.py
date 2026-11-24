"""Process an inbox folder in one run: a run folder out, with a CSV review queue.

A scheduler (``deploy/``) starts one run at a time; each run:

1. picks the documents ready in the inbox: a supported type, not hidden, and
   unmodified for ``settle`` (a folder synced by Google Drive or Dropbox may
   still be writing a file, and neither documents how it writes one);
2. creates its run folder, ``runs/<UTC time>/``, failing if it already exists,
   so two runs never mix and nothing is paid for before that check;
3. extracts every document, logging each by the hash of its bytes, never its
   file name (AGENTS.md invariant 6);
4. writes ``results.jsonl`` (the results as produced, one line per document)
   and ``results.csv`` (one row per field, with empty columns for the
   reviewer's verdict, read back by ``doc_intake.review``), each through a
   temporary file and ``os.replace``, so nobody opens half a file;
5. only then moves the originals to ``documents/`` beside it.

With an acceptance policy (``doc_intake.acceptance``, docs/ARCHITECTURE.md
D22), values read from the image of an accepted field are accepted without
review, except a random audit share sent back to the queue.

If a run stops before step 5, the files are still in the inbox and the next
run processes them again: a document may be paid for twice, never lost
(at-least-once).

A problem with one document becomes its ``failed`` row; it never discards
the others. A file that is not a readable document moves with the run, since
reading it again cannot change. A file the run cannot open, a provider error
(network, rate limit, a rejected request) and a file replaced during the run
stay in the inbox and are tried again by every run until they succeed. A
model with no price stops the run after keeping what is done: every further
call would be paid without a logged cost. Missing OCR data stops it before
the first call.
"""

import csv
import hashlib
import io
import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from doc_intake.acceptance import Acceptance, audit
from doc_intake.core.extract import Pack
from doc_intake.core.ingest import (
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    IngestError,
    OcrDataMissingError,
    ingest,
    require_ocr_data,
)
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import UnknownModelPriceError
from doc_intake.core.result import ExtractedField, ExtractionResult, is_field
from doc_intake.core.runlog import extract_logged, log_unreadable, new_run_id

SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES
RESULTS_NAME = "results.csv"
# The results as the run produced them, one JSON object per document. The
# reviewer edits results.csv in a spreadsheet, which may rewrite a value (a
# date in the local format); doc_intake.review reads the suggestions from here.
COPY_NAME = "results.jsonl"
DOCUMENTS_NAME = "documents"

# What the reviewer fills, empty when written: an empty verdict means not
# reviewed, never confirmed (doc_intake.review, docs/ARCHITECTURE.md D20).
VERDICT_COLUMNS: tuple[str, ...] = ("verdict", "correct_value")
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
    *VERDICT_COLUMNS,
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
    recommendation. It is part of the cell's text, so a reader may see it.
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


LEFT_FOR_NEXT_RUN = "left in the inbox for the next run"


@dataclass(frozen=True, slots=True)
class _Outcome[S: BaseModel]:
    path: Path
    result: ExtractionResult[S]
    # Moved with the run; otherwise left in the inbox for the next one.
    move: bool
    # SHA-256 of the bytes that were extracted, to notice a file replaced
    # before it is moved; None when the file was not read.
    digest: str | None = None


def _left[S: BaseModel](pack: Pack[S], path: Path, note: str) -> _Outcome[S]:
    """A failed row for ``path``, which stays in the inbox; ``pack`` fixes the type."""
    return _Outcome(path, ExtractionResult[S](status="failed", errors=[note]), move=False)


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
    acceptance: Acceptance | None = None,
) -> RunReport:
    """Process the documents ready in ``inbox`` into a new folder under ``runs``.

    Raises ``OcrDataMissingError`` (configuration, not the document) and
    ``FileExistsError`` (this run's folder already exists) before any call.
    """
    documents = ready_documents(inbox, settle=settle, now=now)
    if not documents:
        return RunReport(folder=None, documents=0, needs_review=0, failed=0)
    require_ocr_data(tessdata_dir)

    folder = runs / now.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    runs.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    run_id = new_run_id()
    outcomes: list[_Outcome[S]] = []
    try:
        for path in documents:
            outcome, stop = _process(
                path, pack, provider, tessdata_dir, provider_name, max_retries, run_id, acceptance
            )
            outcomes.append(outcome)
            if stop:
                break
    except BaseException:
        # An interrupt (Ctrl+C, systemctl stop): nothing written or moved, so
        # the next run starts from the same inbox.
        folder.rmdir()
        raise

    outcomes = [_unless_replaced(pack, outcome) for outcome in outcomes]
    _write_copy(folder / COPY_NAME, outcomes)
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
    acceptance: Acceptance | None,
) -> tuple[_Outcome[S], bool]:
    """One document's outcome, and whether the run must stop after it.

    A problem with one document never discards the documents already paid
    for: it becomes that document's ``failed`` row. Notes name only the
    error's class; its message may quote the document or name its path.
    """
    try:
        content = path.read_bytes()
    except OSError as error:  # permissions, a file removed meanwhile
        return _left(pack, path, f"{type(error).__name__}; {LEFT_FOR_NEXT_RUN}"), False
    document_id = hashlib.sha256(content).hexdigest()
    try:
        document = ingest(path, tessdata_dir=tessdata_dir)
    except OcrDataMissingError:
        raise  # configuration, checked before the first call
    except IngestError as error:
        log_unreadable(
            error,
            pack_name=pack.name,
            document_id=document_id,
            run_id=run_id,
            provider_name=provider_name,
        )
        # Reading it again cannot change: it moves with the run. Its name is
        # in the message, and this CSV is the owner's, not a log.
        failed = ExtractionResult[S](status="failed", errors=[str(error)])
        return _Outcome(path, failed, move=True, digest=document_id), False
    try:
        result, _ = extract_logged(
            document,
            pack,
            provider,
            document_id=document_id,
            run_id=run_id,
            provider_name=provider_name,
            max_retries=max_retries,
            accept_from_image=acceptance.fields if acceptance else frozenset(),
        )
    except UnknownModelPriceError as error:
        # Paid, but its cost cannot be logged: every further call would be
        # too. Configuration, so the run stops; what is done is kept.
        note = f"{type(error).__name__}; run stopped: add the model's price, then run again"
        return _left(pack, path, note), True
    except Exception as error:
        # Provider errors (network, rate limit, a rejected request), logged by
        # extract_logged with the calls already paid. Retried by every run
        # until it succeeds; exit 1 on each run tells someone to look.
        return _left(pack, path, f"{type(error).__name__}; {LEFT_FOR_NEXT_RUN}"), False
    if acceptance is not None:
        result = audit(result, acceptance.fields, rate=acceptance.audit_rate, draw=acceptance.draw)
    return _Outcome(path, result, move=True, digest=document_id), False


def _unless_replaced[S: BaseModel](pack: Pack[S], outcome: _Outcome[S]) -> _Outcome[S]:
    """Leave a file whose bytes changed since they were extracted.

    A sync client can write a new version under the same name while the run
    works on other files; moving it would file a version nobody extracted.
    """
    if not outcome.move or outcome.digest is None:
        return outcome
    try:
        unchanged = hashlib.sha256(outcome.path.read_bytes()).hexdigest() == outcome.digest
    except OSError:
        unchanged = False
    if unchanged:
        return outcome
    return _left(pack, outcome.path, f"changed during the run; {LEFT_FOR_NEXT_RUN}")


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
            "note": problems.get(name) or field.reason or _accepted_note(field),
        }
        yield row


def _accepted_note(field: ExtractedField[object]) -> str:
    """Why a value read from the image is not under review: only a policy accepts one."""
    citation = field.citation
    if citation is not None and citation.source == "image":
        return "accepted from the image by the acceptance policy"
    return ""


def _write_copy[S: BaseModel](path: Path, outcomes: list[_Outcome[S]]) -> None:
    lines = (
        json.dumps({"file": o.path.name, "result": o.result.model_dump(mode="json")})
        for o in outcomes
    )
    _write_atomically(path, "".join(line + "\n" for line in lines), encoding="utf-8")


def _write_csv[S: BaseModel](path: Path, outcomes: list[_Outcome[S]]) -> None:
    buffer = io.StringIO(newline="")
    # Every cell quoted: OWASP's other half of the defence. A spreadsheet that
    # splits on ";" (Excel in pt-BR or de-DE) would otherwise start a new cell
    # inside "x;=HYPERLINK(...)", past the guard on the first character.
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, restval="", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for outcome in outcomes:
        for row in _rows(outcome):
            writer.writerow({key: spreadsheet_safe(value) for key, value in row.items()})
    # utf-8-sig writes the BOM Excel needs to open the file as UTF-8.
    _write_atomically(path, buffer.getvalue(), encoding="utf-8-sig")


def _write_atomically(path: Path, text: str, *, encoding: str) -> None:
    """Write through a temporary file, so nobody opens half a file."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding=encoding, newline="")
    temporary.replace(path)  # atomic on one filesystem (os.replace)
