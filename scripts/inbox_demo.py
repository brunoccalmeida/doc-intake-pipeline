"""Show the delivered flow on the demo receipts, replayed: no key, no cost.

    uv run poe inbox-demo

Empties ``.cache/inbox-demo``, drops the two synthetic demo receipts in its
``inbox/`` and runs ``uv run poe inbox`` once over it with their recorded
answers. ``receipt.png`` is accepted whole; ``receipt-review.png`` queues its
total for review (read from the image). Open the printed ``results.csv``.

The provider and model are the ones the answers were recorded with, set here
rather than read from ``.env``: another model would ask for other recordings.
"""

import shutil
import sys
from datetime import timedelta
from pathlib import Path

from doc_intake.core.config import Settings
from evals.recording import RecordingStore, ReplayProvider
from scripts.logs import configure_run_log
from scripts.run_inbox import process

DEMO = Path("demo")
RECEIPTS = ("receipt.png", "receipt-review.png")
DEFAULT_ROOT = Path(".cache/inbox-demo")


def main(root: Path = DEFAULT_ROOT) -> int:
    settings = Settings(provider="claude", claude_model="claude-opus-5-5")
    configure_run_log(settings.log_level)
    shutil.rmtree(root, ignore_errors=True)
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    for name in RECEIPTS:
        shutil.copy(DEMO / name, inbox / name)
    provider = ReplayProvider(
        RecordingStore(DEMO / "recordings"),
        provider=settings.provider,
        model=settings.model,
        record_command="see demo/README.md, 'What it replays'",
    )
    # Settle 0: the files were copied a moment ago and nothing else writes them.
    return process(settings, provider, inbox, root / "runs", settle=timedelta(0))


if __name__ == "__main__":
    sys.exit(main())
