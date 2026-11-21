"""``uv run poe eval``: replay recordings, write the report, gate on the baseline.

End to end on one real golden receipt (needs ``uv run poe fetch-golden``):
a fake provider records an answer into a temporary recordings directory, then
the script replays it, as CI does, with no key and no network.
"""

import json
import uuid
from pathlib import Path

import pytest

from core.config import Settings
from core.ingest import ingest
from core.llm import LLMRequest, LLMResponse
from core.pricing import UnknownModelPriceError
from evals.recording import RecordingProvider, RecordingStore
from evals.run import run_eval
from evals.sroie import MANIFEST_PATH, load_manifest
from packs.receipt import RECEIPT
from providers import MissingCredentialError
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
