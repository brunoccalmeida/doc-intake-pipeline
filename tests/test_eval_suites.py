"""``uv run poe eval --suite fatura``: the invoice golden set, gated like the receipts (#69).

The FATURA recordings answer invoices licensed CC BY 4.0, so they are
committed with the set (``evals/recordings/fatura``); these tests point the
suite at a temporary directory instead, so nothing is written there.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.packs.invoice import INVOICE
from evals import suites
from evals.fatura import GOLDEN_DIR
from evals.readme import markers
from evals.recording import RecordingProvider, RecordingStore
from evals.run import run_eval
from scripts.run_eval import main

FIRST_ID = "Template50_Instance0"
FIELDS = list(INVOICE.schema.model_fields)


class Answer:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text=self.text, input_tokens=1_000, output_tokens=200, model="claude-opus-5-5"
        )


@pytest.fixture
def fatura(no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The fatura suite on one invoice, recording into ``tmp_path``."""
    directory = tmp_path / "recordings"
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("DOC_INTAKE_MAX_RETRIES", "2")

    def recordings_dir(_: Settings) -> Path:
        return directory

    one = replace(suites.SUITES["fatura"], recordings_dir=recordings_dir, ids=lambda: [FIRST_ID])
    monkeypatch.setitem(suites.SUITES, "fatura", one)
    return directory


def record(directory: Path, answer: str) -> None:
    settings = Settings()
    provider = RecordingProvider(
        Answer(answer), RecordingStore(directory), provider=settings.provider, model=settings.model
    )
    run_eval(
        [FIRST_ID],
        INVOICE,
        provider,
        golden_dir=GOLDEN_DIR,
        tessdata_dir=settings.tessdata_dir,
        run_id="recording",
        provider_name=settings.provider,
    )


def golden_answer(**changes: object) -> str:
    golden = json.loads((GOLDEN_DIR / f"{FIRST_ID}.json").read_text(encoding="utf-8"))
    for name, value in changes.items():
        golden[name]["value"] = value
    return json.dumps(golden)


def baseline(tmp_path: Path, correct: int = 1) -> Path:
    path = tmp_path / "baseline.json"
    content = {
        "documents": 1,
        "fields": dict.fromkeys(FIELDS, correct),
        "wrong_accepted": dict.fromkeys(FIELDS, 0),
    }
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def readme(tmp_path: Path, block: str) -> Path:
    start, end = markers("fatura")
    path = tmp_path / "README.md"
    path.write_text(f"# Title\n\n{start}\n{block}\n{end}\n\nAfter.\n", encoding="utf-8")
    return path


def run(tmp_path: Path, *extra: str) -> int:
    return main(
        [
            "--suite",
            "fatura",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--readme",
            str(tmp_path / "README.md"),
            "--report",
            str(tmp_path / "report.md"),
            *extra,
        ]
    )


def test_the_fatura_suite_scores_the_invoice_golden_set() -> None:
    suite = suites.SUITES["fatura"]
    assert suite.pack is INVOICE
    assert len(suite.ids()) == 20
    assert suite.golden_dir(Settings()) == GOLDEN_DIR
    assert suite.baseline.name == "baseline-fatura.json"


def test_the_default_suite_is_still_sroie() -> None:
    # Every documented `uv run poe eval` command keeps its meaning.
    assert suites.DEFAULT == "sroie"


def test_replay_at_the_baseline_passes(fatura: Path, tmp_path: Path) -> None:
    record(fatura, golden_answer())
    baseline(tmp_path)
    readme(tmp_path, "old")

    assert run(tmp_path, "--update-readme") == 0

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "**Gate: passed.**" in report
    assert "template-generated" in report


def test_a_worse_invoice_answer_fails_the_gate_naming_the_field(
    fatura: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record(fatura, golden_answer(seller_name="Someone Else Ltd"))
    baseline(tmp_path)
    readme(tmp_path, "old")

    assert run(tmp_path) == 1

    assert "seller_name: 0/1 correct, below the baseline of 1/1" in capsys.readouterr().err


def test_the_readme_block_of_the_suite_is_the_one_written(fatura: Path, tmp_path: Path) -> None:
    record(fatura, golden_answer())
    baseline(tmp_path)
    sroie_start, sroie_end = markers("sroie")
    path = readme(tmp_path, "old")
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n{sroie_start}\nreceipts\n{sroie_end}\n",
        encoding="utf-8",
    )

    assert run(tmp_path, "--update-readme") == 0

    text = path.read_text(encoding="utf-8")
    assert "public template-generated invoices" in text
    assert f"{sroie_start}\nreceipts\n{sroie_end}" in text
    assert "per invoice" in text
