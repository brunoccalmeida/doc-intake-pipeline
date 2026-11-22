"""Process an inbox folder once: the command a scheduler runs (``deploy/``).

    uv run poe inbox INBOX RUNS                      # paid: the configured provider
    uv run poe inbox INBOX RUNS --replay DIR         # recorded answers: no key, no cost
    uv run poe inbox INBOX RUNS --settle 0           # take files written just now

Each run creates ``RUNS/<UTC time>/`` with ``results.csv`` (one row per field;
the review queue is the rows whose ``field_status`` is ``needs_review``) and
the processed originals in ``documents/``; see ``doc_intake.batch``.

Prints one summary line on stdout; the run log (``doc_intake.core.runlog``) goes
to stderr, one line per document, by hash, never by file name.

Exits 1 when a document failed, so the scheduler marks the run as failed and
someone looks; ``needs_review`` is the queue working, and exits 0.

Configuration is checked before the inbox is read (fail fast): an unpriced
model or a missing key stops the run before anything is paid for.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from doc_intake.batch import run_inbox
from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import price_of
from doc_intake.packs.receipt import RECEIPT
from doc_intake.providers import make_provider
from evals.recording import RecordingStore, ReplayProvider
from scripts.logs import configure_run_log

# Neither Google Drive nor Dropbox documents how it writes a synced file, so a
# file is taken only once it has not changed for this long (own judgment).
DEFAULT_SETTLE_SECONDS = 60


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
    args = parser.parse_args(argv)
    inbox: Path = args.inbox
    runs: Path = args.runs
    settle: int = args.settle
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
            record_command=f"uv run poe extract --record {replay} <file>",
        )
    else:
        provider = make_provider(settings)

    return process(settings, provider, inbox, runs, settle=timedelta(seconds=settle))


def process(
    settings: Settings, provider: LLMProvider, inbox: Path, runs: Path, *, settle: timedelta
) -> int:
    """One run, its summary line on stdout, and the exit code (module docstring)."""
    report = run_inbox(
        inbox,
        runs,
        RECEIPT,
        provider,
        tessdata_dir=settings.tessdata_dir,
        provider_name=settings.provider,
        max_retries=settings.max_retries,
        settle=settle,
        now=datetime.now(UTC),
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
