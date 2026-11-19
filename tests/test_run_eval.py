"""The eval runner: read, extract and score each golden document, and meter the calls.

A fake provider answers (AGENTS.md invariant 4). The happy path reads one real
golden receipt, so it needs ``uv run poe fetch-golden`` and the OCR data, like
the other golden-set tests; the unreadable case builds its own blank image.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from core.config import Settings
from core.ingest import OcrDataMissingError
from core.llm import LLMRequest, LLMResponse
from core.result import Citation, ExtractedField
from evals.run import run_eval
from evals.sroie import MANIFEST_PATH, load_manifest
from packs.receipt import RECEIPT, Receipt

SETTINGS = Settings()
FIRST_ID = load_manifest(MANIFEST_PATH).receipts[0].id


@dataclass
class ScriptedProvider:
    """Answers every request with ``text`` and keeps the requests."""

    text: str
    model: str = "claude-opus-5-5"
    requests: list[LLMRequest] = field(default_factory=list[LLMRequest])

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(text=self.text, input_tokens=1_000, output_tokens=200, model=self.model)


def golden_text(document_id: str) -> str:
    return (SETTINGS.sroie_dir / f"{document_id}.json").read_text(encoding="utf-8")


def test_golden_answer_scores_every_field_correct_and_meters_the_call() -> None:
    provider = ScriptedProvider(golden_text(FIRST_ID))

    run = run_eval(
        [FIRST_ID],
        RECEIPT,
        provider,
        golden_dir=SETTINGS.sroie_dir,
        tessdata_dir=SETTINGS.tessdata_dir,
    )

    [score] = run.scores
    assert score.id == FIRST_ID
    assert set(score.fields.values()) == {"correct"}
    assert run.usage.calls == 1
    assert (run.usage.input_tokens, run.usage.output_tokens) == (1_000, 200)
    assert run.usage.cost_usd == Decimal("0.008")  # 1000 x $4/M + 200 x $20/M
    assert run.usage.models == ("claude-opus-5-5",)


def write_golden(directory: Path, document_id: str) -> None:
    def cited[T](value: T) -> ExtractedField[T]:
        return ExtractedField[T](value=value, citation=Citation(page=1, quote="q"), reason=None)

    golden = Receipt(
        company=cited("ACME"),
        address=cited("JALAN MAJU"),
        date=cited(date(2018, 1, 15)),
        total=cited(Decimal("9.00")),
        currency=cited("MYR"),
    )
    (directory / f"{document_id}.json").write_text(golden.model_dump_json(), encoding="utf-8")


def test_an_unreadable_document_is_scored_failed_without_calling_the_provider(
    tmp_path: Path,
) -> None:
    write_golden(tmp_path, "X1")
    Image.new("RGB", (400, 200), "white").save(tmp_path / "X1.jpg")
    provider = ScriptedProvider(json.dumps({}))

    run = run_eval(
        ["X1"], RECEIPT, provider, golden_dir=tmp_path, tessdata_dir=SETTINGS.tessdata_dir
    )

    [score] = run.scores
    assert score.status == "failed"
    assert score.error == "EmptyDocumentError"
    assert provider.requests == []
    assert run.usage.calls == 0
    assert run.usage.cost_usd == 0


def test_missing_ocr_data_stops_the_run_instead_of_scoring_a_failure(tmp_path: Path) -> None:
    write_golden(tmp_path, "X1")
    Image.new("RGB", (400, 200), "white").save(tmp_path / "X1.jpg")

    with pytest.raises(OcrDataMissingError):
        run_eval(
            ["X1"],
            RECEIPT,
            ScriptedProvider("{}"),
            golden_dir=tmp_path,
            tessdata_dir=tmp_path / "no-tessdata",
        )
