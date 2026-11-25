"""The eval runner: read, extract and score each golden document, and meter the calls.

A fake provider answers (AGENTS.md invariant 4). The happy path reads one real
golden receipt, so it needs ``uv run poe fetch-golden`` and the OCR data, like
the other golden-set tests; the unreadable case builds its own blank image.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from doc_intake.core.config import Settings
from doc_intake.core.ingest import OcrDataMissingError
from doc_intake.core.llm import LLMRequest, LLMResponse
from doc_intake.core.result import Citation, ExtractedField
from doc_intake.core.runlog import RUN_LOGGER, RunLogEntry
from doc_intake.packs.receipt import RECEIPT, Receipt
from evals.run import EvalRun, Usage, run_eval
from evals.sroie import MANIFEST_PATH, load_manifest

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


def test_golden_answer_scores_every_field_correct_and_meters_the_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)
    provider = ScriptedProvider(golden_text(FIRST_ID))

    run = run_eval(
        [FIRST_ID],
        RECEIPT,
        provider,
        golden_dir=SETTINGS.sroie_dir,
        tessdata_dir=SETTINGS.tessdata_dir,
        run_id="run-1",
        provider_name="scripted",
    )

    [score] = run.scores
    assert score.id == FIRST_ID
    assert set(score.fields.values()) == {"correct"}
    assert run.usage.documents == 1
    assert run.usage.calls == 1
    assert (run.usage.input_tokens, run.usage.output_tokens) == (1_000, 200)
    assert run.usage.cost_usd == Decimal("0.008")  # 1000 x $4/M + 200 x $20/M
    assert run.usage.average_cost_usd == Decimal("0.008")
    assert run.usage.models == ("claude-opus-5-5",)
    [line] = logged(caplog)
    assert (line["run_id"], line["document_id"], line["provider"]) == (
        "run-1",
        FIRST_ID,
        "scripted",
    )


def test_the_run_names_image_read_fields_and_applies_a_receipts_accepted_ones() -> None:
    # Golden citations are read from the image (D12): every valued field.
    answer = golden_text(FIRST_ID)
    image_read = frozenset(
        name for name, field in json.loads(answer).items() if field["citation"] is not None
    )
    assert "total" in image_read

    def scored(accept: dict[str, frozenset[str]] | None) -> EvalRun:
        return run_eval(
            [FIRST_ID],
            RECEIPT,
            ScriptedProvider(answer),
            golden_dir=SETTINGS.sroie_dir,
            tessdata_dir=SETTINGS.tessdata_dir,
            run_id="run-1",
            provider_name="scripted",
            accept=accept,
        )

    default, accepted = scored(None), scored({FIRST_ID: frozenset({"total"})})

    assert default.from_image == {FIRST_ID: image_read}
    assert default.scores[0].routes["total"] == "review"
    assert accepted.scores[0].routes == default.scores[0].routes | {"total": "accepted"}


def logged(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == RUN_LOGGER]


def test_average_cost_is_over_every_document_rounded_to_a_millionth_of_a_dollar() -> None:
    usage = Usage.of(
        [entry(cost="0.008"), entry(cost="0.008"), entry(cost="0", calls=0)],
    )
    assert usage.documents == 3
    assert usage.cost_usd == Decimal("0.016")
    assert usage.average_cost_usd == Decimal("0.005333")  # 0.016 / 3, half-even


def test_a_run_without_documents_has_no_average() -> None:
    assert Usage.of([]).average_cost_usd is None


def entry(*, cost: str, calls: int = 1) -> RunLogEntry:
    return RunLogEntry(
        timestamp=datetime(2026, 11, 19, tzinfo=UTC),
        run_id="run-1",
        document_id="X",
        pack="receipt",
        provider="scripted",
        models=("claude-opus-5-5",) if calls else (),
        status="ok" if calls else "failed",
        errors=[] if calls else ["EmptyDocumentError"],
        calls=calls,
        retries=0,
        input_tokens=1_000 * calls,
        output_tokens=200 * calls,
        latency_ms=0,
        cost_usd=Decimal(cost),
    )


def write_golden(directory: Path, document_id: str) -> None:
    def cited[T](value: T) -> ExtractedField[T]:
        return ExtractedField[T](
            value=value, citation=Citation(page=1, source="text", quote="q"), reason=None
        )

    not_printed = ExtractedField[Decimal](value=None, citation=None, reason="not printed")
    golden = Receipt(
        company=cited("ACME"),
        address=cited("JALAN MAJU"),
        date=cited(date(2018, 1, 15)),
        total=cited(Decimal("9.00")),
        currency=cited("MYR"),
        net=not_printed,
        tax=not_printed,
        rounding=not_printed,
    )
    (directory / f"{document_id}.json").write_text(golden.model_dump_json(), encoding="utf-8")


def test_an_unreadable_document_is_scored_failed_without_calling_the_provider(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=RUN_LOGGER)
    write_golden(tmp_path, "X1")
    Image.new("RGB", (400, 200), "white").save(tmp_path / "X1.jpg")
    provider = ScriptedProvider(json.dumps({}))

    run = run_eval(
        ["X1"],
        RECEIPT,
        provider,
        golden_dir=tmp_path,
        tessdata_dir=SETTINGS.tessdata_dir,
        run_id="run-1",
        provider_name="scripted",
    )

    [score] = run.scores
    assert score.status == "failed"
    assert score.error == "EmptyDocumentError"
    assert provider.requests == []
    assert run.usage.documents == 1
    assert run.usage.calls == 0
    assert run.usage.cost_usd == 0
    [line] = logged(caplog)
    assert (line["document_id"], line["status"], line["errors"]) == (
        "X1",
        "failed",
        ["EmptyDocumentError"],
    )


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
            run_id="run-1",
            provider_name="scripted",
        )
