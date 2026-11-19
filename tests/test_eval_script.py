"""``uv run poe eval``: replay recordings, write the report, gate on the baseline.

End to end on one real golden receipt (needs ``uv run poe fetch-golden``):
a fake provider records an answer into a temporary recordings directory, then
the script replays it, as CI does, with no key and no network.
"""

import json
from pathlib import Path

import pytest

from core.config import Settings
from core.llm import LLMRequest, LLMResponse
from evals.recording import RecordingProvider, RecordingStore
from evals.run import run_eval
from evals.sroie import MANIFEST_PATH, load_manifest
from packs.receipt import RECEIPT
from providers import MissingApiKeyError
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
    run_eval([FIRST_ID], RECEIPT, provider, golden_dir=GOLDEN, tessdata_dir=settings.tessdata_dir)


def golden_answer(**changes: object) -> str:
    golden = json.loads((GOLDEN / f"{FIRST_ID}.json").read_text(encoding="utf-8"))
    for name, value in changes.items():
        golden[name]["value"] = value
    return json.dumps(golden)


def baseline(tmp_path: Path, correct: int = 1) -> Path:
    path = tmp_path / "baseline.json"
    fields = dict.fromkeys(FIELDS, correct)
    path.write_text(json.dumps({"documents": 1, "fields": fields}), encoding="utf-8")
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


def test_a_worse_recording_fails_the_gate_naming_the_field(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record(recordings, golden_answer(total="0.01"))
    baseline(tmp_path)

    code, report = run(tmp_path)

    assert code == 1
    assert "- total: 0/1 correct, below the baseline of 1/1" in report
    assert "total: 0/1 correct" in capsys.readouterr().err


def test_a_missing_recording_fails_naming_the_fix(
    recordings: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline(tmp_path)

    code, _ = run(tmp_path)

    assert code == 1
    assert "poe eval --record" in capsys.readouterr().err


def test_update_baseline_writes_the_current_scores(recordings: Path, tmp_path: Path) -> None:
    record(recordings, golden_answer(total="0.01"))
    path = baseline(tmp_path, correct=0)

    code, _ = run(tmp_path, "--update-baseline")

    assert code == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["fields"]["total"] == 0
    assert written["fields"]["company"] == 1


def test_record_without_an_api_key_fails_before_reading_anything(
    recordings: Path, tmp_path: Path
) -> None:
    with pytest.raises(MissingApiKeyError, match="DOC_INTAKE_ANTHROPIC_API_KEY"):
        run(tmp_path, "--record")
