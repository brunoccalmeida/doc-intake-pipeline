"""The demo video's inputs stay in step with the code it films (``demo/README.md``).

The video replays recorded answers, keyed by the prompt, schema, OCR text and
model: a change to any of them silently leaves the demo with nothing to replay.
These tests fail first, naming the re-recording, instead of a broken video.
"""

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from demo import show_result
from scripts.extract_document import main

DEMO = Path("demo")


def test_the_demo_receipt_replays_with_every_field_cited_but_the_currency(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The settings the tape exports and the recording was made with: stated
    # here too, so a .env that picks another model cannot change the key.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    code = main(["--replay", str(DEMO / "recordings"), str(DEMO / "receipt.png")])

    captured = capsys.readouterr()
    assert code == 0, captured.err
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    fields = result["fields"]
    # No currency is printed on the receipt: null with a reason, never a guess.
    assert fields["currency"]["value"] is None
    assert fields["currency"]["reason"]
    for name in ("company", "address", "date", "total"):
        assert fields[name]["citation"]["source"] == "text", name


def test_the_regression_patch_still_applies() -> None:
    git = shutil.which("git")
    assert git is not None, "git is needed to check demo/regression.patch"

    # A fixed argument list with no shell and no outside input.
    checked = subprocess.run(  # noqa: S603
        [git, "apply", "--check", str(DEMO / "regression.patch")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr


def test_the_result_is_shown_one_line_per_field_with_its_evidence(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    result: dict[str, object] = {
        "status": "ok",
        "fields": {
            "total": {
                "value": "23.40",
                "citation": {"page": 1, "source": "text", "quote": "TOTAL 23.40"},
                "reason": None,
            },
            "currency": {"value": None, "citation": None, "reason": "no currency is printed"},
        },
        "errors": [],
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(result)))

    show_result.main()

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "status: ok"
    assert lines[1].split() == ["total", "23.40", "<-", "page", "1", "text:", '"TOTAL', '23.40"']
    assert lines[2].split() == ["currency", "null", "<-", "no", "currency", "is", "printed"]
