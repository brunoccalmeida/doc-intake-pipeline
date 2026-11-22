"""``uv run poe inbox-demo``: the delivered flow on the demo receipts, replayed (no cost)."""

import csv
from pathlib import Path

import pytest

from scripts import inbox_demo


def test_the_demo_fills_a_fresh_inbox_and_queues_one_field_for_review(
    no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Another model in the environment must not change which answers replay.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "openai")
    root = tmp_path / "inbox-demo"
    (root / "inbox").mkdir(parents=True)
    (root / "inbox" / "left-over.png").write_bytes(b"from an earlier demo")

    assert inbox_demo.main(root) == 0

    [folder] = list((root / "runs").iterdir())
    documents = sorted(p.name for p in (folder / "documents").iterdir())
    assert documents == ["receipt-review.png", "receipt.png"]  # the left-over is gone
    with (folder / "results.csv").open(encoding="utf-8-sig", newline="") as file:
        queue = [row for row in csv.DictReader(file) if row["field_status"] == "needs_review"]
    assert [(row["file"], row["field"]) for row in queue] == [("receipt-review.png", "total")]
