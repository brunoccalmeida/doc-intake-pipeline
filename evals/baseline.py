"""The committed baseline and the gate: no field may score below it.

The baseline stores correct counts, not percentages: counts are exact, and a
percentage of a 20-document set hides that one document moved. Replay is
deterministic, so the tolerance is zero (``docs/ARCHITECTURE.md`` D4). A
better score passes; raising the baseline to it is a deliberate commit
(``uv run poe eval --update-baseline``), so the bar only moves in review.
"""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from core.result import StrictModel

BASELINE_PATH = Path(__file__).parent / "baseline.json"
UPDATE_COMMAND = "uv run poe eval --update-baseline"

type Accuracy = dict[str, tuple[int, int]]


class Baseline(StrictModel, frozen=True):
    """How many documents were scored and how many each field got right."""

    documents: Annotated[int, Field(ge=1)]
    fields: dict[str, Annotated[int, Field(ge=0)]]


def regressions(accuracy: Accuracy, baseline: Baseline) -> list[str]:
    """Every way ``accuracy`` falls short of ``baseline``; empty means the gate passes."""
    totals = {total for _, total in accuracy.values()}
    if totals != {baseline.documents}:
        scored = ", ".join(str(total) for total in sorted(totals))
        return [f"the eval scored {scored} documents, the baseline {baseline.documents}"]
    found: list[str] = []
    for name, (correct, total) in accuracy.items():
        if name not in baseline.fields:
            found.append(f"{name}: no baseline; record one with '{UPDATE_COMMAND}'")
        elif correct < baseline.fields[name]:
            found.append(
                f"{name}: {correct}/{total} correct, "
                f"below the baseline of {baseline.fields[name]}/{baseline.documents}"
            )
    found.extend(
        f"{name}: in the baseline but not scored"
        for name in baseline.fields
        if name not in accuracy
    )
    return found


def load_baseline(path: Path) -> Baseline:
    return Baseline.model_validate_json(path.read_text(encoding="utf-8"))


def save_baseline(path: Path, accuracy: Accuracy) -> None:
    totals = {total for _, total in accuracy.values()}
    if len(totals) != 1:
        raise ValueError(f"fields were scored over different numbers of documents: {totals}")
    baseline = Baseline(
        documents=totals.pop(), fields={name: correct for name, (correct, _) in accuracy.items()}
    )
    path.write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
