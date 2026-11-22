"""``uv run poe eval``: replay recordings, write the report, gate on the baseline.

End to end on one real golden receipt (needs ``uv run poe fetch-golden``):
a fake provider records an answer into a temporary recordings directory, then
the script replays it, as CI does, with no key and no network.
"""

import json
import uuid
from pathlib import Path

import pytest

from doc_intake.core.config import Settings
from doc_intake.core.ingest import ingest
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.core.pricing import UnknownModelPriceError
from doc_intake.packs.receipt import RECEIPT
from doc_intake.providers import MissingCredentialError
from evals.readme import END, START
from evals.recording import RecordingProvider, RecordingStore
from evals.run import run_eval
from evals.sroie import MANIFEST_PATH, load_manifest
from scripts.run_eval import main

GOLDEN = Settings().sroie_dir
FIRST_ID = load_manifest(MANIFEST_PATH).receipts[0].id
FIELDS = list(RECEIPT.schema.model_fields)


class Answer:
    """Answers with ``text``; stands in for the real provider while recording."""

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text=self.text, input_tokens=1_000, output_tokens=200, model="claude-opus-5-5"
        )


@pytest.fixture
def recordings(no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "recordings"
    monkeypatch.setenv("DOC_INTAKE_RECORDINGS_DIR", str(directory))
    # Environment wins over .env: a developer's .env (another provider, model or
    # retry count) must not change the key or the expected error.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("DOC_INTAKE_MAX_RETRIES", "2")
    return directory


def record(directory: Path, answer: str) -> None:
    settings = Settings()
    provider = RecordingProvider(
        Answer(answer), RecordingStore(directory), provider=settings.provider, model=settings.model
    )
    run_eval(
        [FIRST_ID],
        RECEIPT,
        provider,
        golden_dir=GOLDEN,
        tessdata_dir=settings.tessdata_dir,
        run_id="recording",
        provider_name=settings.provider,
    )


def golden_answer(**changes: object) -> str:
    golden = json.loads((GOLDEN / f"{FIRST_ID}.json").read_text(encoding="utf-8"))
    for name, value in changes.items():
        golden[name]["value"] = value
    return json.dumps(golden)


def wrong_total_from_page_text() -> str:
    """A wrong total cited from the OCR text, so the engine accepts it without review.

    The golden citations are read from the image (D12) and would all go to
    review; any word of the page text is a quote the engine can check.
    """
    document = ingest(GOLDEN / f"{FIRST_ID}.jpg", tessdata_dir=Settings().tessdata_dir)
    answer = json.loads(golden_answer(total="0.01"))
    answer["total"]["citation"] = {
        "page": 1,
        "source": "text",
        "quote": document.pages[0].text.split()[0],
    }
    return json.dumps(answer)


def baseline(tmp_path: Path, correct: int = 1, wrong_accepted: int = 0) -> Path:
    path = tmp_path / "baseline.json"
    content = {
        "documents": 1,
        "fields": dict.fromkeys(FIELDS, correct),
        "wrong_accepted": dict.fromkeys(FIELDS, wrong_accepted),
    }
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def run(tmp_path: Path, *extra: str) -> tuple[int, str]:
    report = tmp_path / "report.md"
    args = ["--ids", FIRST_ID, "--baseline", str(tmp_path / "baseline.json")]
    code = main([*args, "--report", str(report), *extra])
    return code, report.read_text(encoding="utf-8") if report.exists() else ""


def test_replay_at_the_baseline_passes_and_writes_the_report(
    recordings: Path, tmp_path: Path
) -> None:
    record(recordings, golden_answer())
    baseline(tmp_path)

    code, report = run(tmp_path)

    assert code == 0
    assert "**Gate: passed.**" in report


def test_each_document_is_logged_as_a_json_line_and_the_summary_shows_the_average(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record(recordings, golden_answer())
    baseline(tmp_path)

    run(tmp_path)

    err = capsys.readouterr().err.splitlines()
    [line] = [json.loads(text) for text in err if text.startswith("{")]
    assert line["document_id"] == FIRST_ID
    assert line["provider"] == "claude"
    assert line["cost_usd"] == "0.008"
    assert uuid.UUID(line["run_id"]).version == 7
    assert any("cost_usd=0.008 average_cost_usd=0.008000" in text for text in err)


def test_a_model_without_a_price_fails_before_reading_anything(
    recordings: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "model-x")
    # Nothing is recorded: without the price check first, this would fail on
    # the missing recording instead (or, with --record, after a paid call).
    with pytest.raises(UnknownModelPriceError, match="'model-x'"):
        run(tmp_path)


def test_a_worse_recording_fails_the_gate_naming_the_field(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record(recordings, golden_answer(total="0.01"))
    baseline(tmp_path)

    code, report = run(tmp_path)

    assert code == 1
    assert "- total: 0/1 correct, below the baseline of 1/1" in report
    assert "total: 0/1 correct" in capsys.readouterr().err


def test_a_wrong_value_accepted_without_review_fails_the_gate_at_equal_accuracy(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The accuracy baseline already allows the wrong total (0 correct), so only
    # the wrong-accepted count can stop it reaching a client unchecked (#38).
    record(recordings, wrong_total_from_page_text())
    path = baseline(tmp_path)
    content = json.loads(path.read_text(encoding="utf-8"))
    content["fields"]["total"] = 0
    path.write_text(json.dumps(content), encoding="utf-8")

    code, report = run(tmp_path)

    assert code == 1
    expected = "total: 1 wrong values accepted without review, above the baseline of 0"
    assert f"- {expected}" in report
    assert expected in capsys.readouterr().err


def test_a_missing_recording_fails_naming_the_fix(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline(tmp_path)

    code, _ = run(tmp_path)

    assert code == 1
    assert "poe eval --record" in capsys.readouterr().err


def test_update_baseline_writes_the_current_scores(recordings: Path, tmp_path: Path) -> None:
    record(recordings, wrong_total_from_page_text())
    path = baseline(tmp_path, correct=0)

    code, _ = run(tmp_path, "--update-baseline")

    assert code == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["fields"]["total"] == 0
    assert written["fields"]["company"] == 1
    assert written["wrong_accepted"]["total"] == 1
    assert written["wrong_accepted"]["company"] == 0


def test_record_without_an_api_key_fails_before_reading_anything(
    recordings: Path, tmp_path: Path
) -> None:
    with pytest.raises(MissingCredentialError, match="DOC_INTAKE_ANTHROPIC_API_KEY"):
        run(tmp_path, "--record")


@pytest.fixture
def one_receipt_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The whole set is the first receipt: a full run (no ``--ids``) at test size."""
    manifest = load_manifest(MANIFEST_PATH)
    path = tmp_path / "manifest.json"
    one = manifest.model_copy(update={"receipts": manifest.receipts[:1], "size": 1})
    path.write_text(one.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("scripts.run_eval.MANIFEST_PATH", path)


def readme(tmp_path: Path, block: str) -> Path:
    path = tmp_path / "README.md"
    path.write_text(f"# Title\n\n{START}\n{block}\n{END}\n\nAfter.\n", encoding="utf-8")
    return path


def run_full(tmp_path: Path, *extra: str) -> int:
    args = ["--baseline", str(tmp_path / "baseline.json"), "--readme", str(tmp_path / "README.md")]
    return main([*args, "--report", str(tmp_path / "report.md"), *extra])


@pytest.mark.usefixtures("one_receipt_set")
def test_a_stale_readme_summary_fails_the_full_run_naming_the_fix(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record(recordings, golden_answer())
    baseline(tmp_path)
    readme(tmp_path, "old numbers")

    code = run_full(tmp_path)

    assert code == 1
    assert "poe eval --update-readme" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "poe eval --update-readme" in capsys.readouterr().err


@pytest.mark.usefixtures("one_receipt_set")
def test_update_readme_writes_the_summary_and_the_next_run_passes(
    recordings: Path, tmp_path: Path
) -> None:
    record(recordings, golden_answer())
    baseline(tmp_path)
    path = readme(tmp_path, "old numbers")

    assert run_full(tmp_path, "--update-readme") == 0

    written = path.read_bytes().decode("utf-8")
    assert "Measured on 1 public scanned receipts, 5 values in all" in written
    assert written.startswith("# Title\n\n")
    assert written.endswith(f"{END}\n\nAfter.\n")
    assert "\r\n" not in written  # the repository stores LF (.gitattributes)
    assert run_full(tmp_path) == 0


@pytest.mark.usefixtures("one_receipt_set")
def test_a_regression_does_not_advise_updating_the_readme(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fix for a worse score is the code, not the README: updating it would
    # publish the worse numbers.
    record(recordings, golden_answer(total="0.01"))
    baseline(tmp_path)
    readme(tmp_path, "old numbers")

    code = run_full(tmp_path)

    assert code == 1
    assert "total: 0/1 correct" in capsys.readouterr().err
    assert "update-readme" not in (tmp_path / "report.md").read_text(encoding="utf-8")


@pytest.mark.usefixtures("one_receipt_set")
def test_update_readme_below_the_baseline_leaves_the_readme_alone(
    recordings: Path, tmp_path: Path
) -> None:
    record(recordings, golden_answer(total="0.01"))
    baseline(tmp_path)
    path = readme(tmp_path, "old numbers")

    assert run_full(tmp_path, "--update-readme") == 1
    assert "old numbers" in path.read_text(encoding="utf-8")


def test_a_subset_leaves_the_readme_alone(recordings: Path, tmp_path: Path) -> None:
    # A subset cannot match the README's whole-set numbers; its gate fails anyway.
    record(recordings, golden_answer())
    baseline(tmp_path)
    path = readme(tmp_path, "old numbers")

    code, _ = run(tmp_path, "--readme", str(path))

    assert code == 0
    assert "old numbers" in path.read_text(encoding="utf-8")


def test_update_readme_refuses_a_subset(recordings: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        run(tmp_path, "--update-readme")

    assert raised.value.code == 2
