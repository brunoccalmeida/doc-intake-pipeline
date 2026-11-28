"""Process an inbox folder once: the command a scheduler runs (``deploy/``).

    uv run poe inbox INBOX RUNS                      # paid: the configured provider
    uv run poe inbox INBOX RUNS --replay DIR         # recorded answers: no key, no cost
    uv run poe inbox INBOX RUNS --settle 0           # take files written just now
    uv run poe inbox INBOX RUNS --pack invoice       # default pack: receipt

Each run creates ``RUNS/<UTC time>/`` with ``results.csv`` (one row per field;
the review queue is the rows whose ``field_status`` is ``needs_review``) and
the processed originals in ``documents/``; see ``doc_intake.batch``.

Prints one summary line on stdout; the run log (``doc_intake.core.runlog``) goes
to stderr, one line per document, by hash, never by file name.

Exits 1 when a document failed, so the scheduler marks the run as failed and
someone looks; ``needs_review`` is the queue working, and exits 0.

Configuration is checked before the inbox is read (fail fast): an unpriced
model, a missing key or an acceptance policy that cannot be used
(``DOC_INTAKE_ACCEPTANCE_POLICY``, docs/ARCHITECTURE.md D22), such as one
calibrated on another pack, stops the run before anything is paid for.
"""

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from doc_intake.acceptance import Acceptance, accepted_fields, load_policy
from doc_intake.batch import run_inbox
from doc_intake.core.config import Settings
from doc_intake.core.extract import Pack
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import price_of
from doc_intake.packs.invoice import INVOICE
from doc_intake.packs.receipt import RECEIPT
from doc_intake.providers import make_provider
from evals.recording import RecordingStore, ReplayProvider
from scripts.logs import configure_run_log
from scripts.packs import add_pack_argument

# Neither Google Drive nor Dropbox documents how it writes a synced file, so a
# file is taken only once it has not changed for this long (own judgment).
DEFAULT_SETTLE_SECONDS = 60

# Which accepted values go to the audit: unpredictable, so no pattern in the
# documents can steer which values are checked (a test replaces it).
audit_draw = random.SystemRandom().random


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("inbox", type=Path, help="folder the documents arrive in")
    parser.add_argument("runs", type=Path, help="folder that receives one folder per run")
    parser.add_argument(
        "--settle",
        type=int,
        default=DEFAULT_SETTLE_SECONDS,
        metavar="SECONDS",
        help=f"take a file unmodified for this long (default {DEFAULT_SETTLE_SECONDS})",
    )
    parser.add_argument("--replay", type=Path, metavar="DIR", help="replay stored answers")
    add_pack_argument(parser)
    args = parser.parse_args(argv)
    inbox: Path = args.inbox
    runs: Path = args.runs
    settle: int = args.settle
    replay: Path | None = args.replay

    # One call per pack, not a lookup: each pack keeps its own schema type.
    match args.pack:
        case INVOICE.name:
            return _run(INVOICE, inbox, runs, settle=settle, replay=replay)
        case _:
            return _run(RECEIPT, inbox, runs, settle=settle, replay=replay)


def _run[S: BaseModel](
    pack: Pack[S], inbox: Path, runs: Path, *, settle: int, replay: Path | None
) -> int:
    settings = Settings()
    configure_run_log(settings.log_level)
    price_of(settings.model)
    acceptance = acceptance_of(settings, pack)
    provider: LLMProvider
    if replay is not None:
        provider = ReplayProvider(
            RecordingStore(replay),
            provider=settings.provider,
            model=settings.model,
            record_command=f"uv run poe extract --record {replay} <file>",
        )
    else:
        provider = make_provider(settings)

    return process(
        settings,
        provider,
        inbox,
        runs,
        pack,
        settle=timedelta(seconds=settle),
        acceptance=acceptance,
    )


def acceptance_of[S: BaseModel](settings: Settings, pack: Pack[S]) -> Acceptance | None:
    """The configured acceptance policy, as a run applies it; None when unset.

    A policy calibrated on another pack raises: its evidence is about fields
    this run does not read (``accepted_fields``).
    """
    if settings.acceptance_policy is None:
        return None
    policy = load_policy(settings.acceptance_policy)
    return Acceptance(
        accepted_fields(policy, pack),
        audit_rate=policy.audit_rate,
        # Looked up at call time, so a test's replacement is the one used.
        draw=lambda: audit_draw(),
    )


def process[S: BaseModel](
    settings: Settings,
    provider: LLMProvider,
    inbox: Path,
    runs: Path,
    pack: Pack[S],
    *,
    settle: timedelta,
    acceptance: Acceptance | None = None,
) -> int:
    """One run, its summary line on stdout, and the exit code (module docstring)."""
    report = run_inbox(
        inbox,
        runs,
        pack,
        provider,
        tessdata_dir=settings.tessdata_dir,
        provider_name=settings.provider,
        max_retries=settings.max_retries,
        settle=settle,
        now=datetime.now(UTC),
        acceptance=acceptance,
    )
    if report.folder is None:
        print("nothing ready in the inbox")
        return 0
    print(
        f"{report.folder / 'results.csv'}: {report.documents} documents, "
        f"{report.needs_review} needs review, {report.failed} failed"
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
