"""The committed baseline and the gate, per field.

Two counts are gated (``docs/ARCHITECTURE.md`` D4 and D16):

- **correct** values may not fall below the baseline;
- **wrong values accepted without review** may not rise above it. A wrong
  value moving from review to accepted keeps the accuracy unchanged, so only
  this count sees it reach a client unchecked (invariant 1).

The baseline stores counts, not percentages: counts are exact, and a
percentage of a 20-document set hides that one document moved. Replay is
deterministic, so the tolerance is zero. A better score passes; moving the
baseline to it is a deliberate commit (``uv run poe eval --update-baseline``),
so the bar only moves in review.
"""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from doc_intake.core.result import StrictModel
from evals.scoring import ReviewLoad

BASELINE_PATH = Path(__file__).parent / "baseline.json"
UPDATE_COMMAND = "uv run poe eval --update-baseline"

type Accuracy = dict[str, tuple[int, int]]
type Load = dict[str, ReviewLoad]


class Baseline(StrictModel, frozen=True):
    """Documents scored, and per field the correct values and the wrong ones accepted."""

    documents: Annotated[int, Field(ge=1)]
    fields: dict[str, Annotated[int, Field(ge=0)]]
    wrong_accepted: dict[str, Annotated[int, Field(ge=0)]]


def regressions(accuracy: Accuracy, load: Load, baseline: Baseline) -> list[str]:
    """Every way the run falls short of ``baseline``; empty means the gate passes."""
    totals = {total for _, total in accuracy.values()}
    if totals != {baseline.documents}:
        scored = ", ".join(str(total) for total in sorted(totals))
        return [f"the eval scored {scored} documents, the baseline {baseline.documents}"]
    found: list[str] = []
    for name, (correct, total) in accuracy.items():
        if name not in baseline.fields:
            found.append(f"{name}: no baseline; record one with '{UPDATE_COMMAND}'")
            continue
        if correct < baseline.fields[name]:
            found.append(
                f"{name}: {correct}/{total} correct, "
                f"below the baseline of {baseline.fields[name]}/{baseline.documents}"
            )
        if name not in baseline.wrong_accepted:
            found.append(
                f"{name}: no baseline of wrong accepted values; record one with '{UPDATE_COMMAND}'"
            )
        elif load[name].wrong_accepted > baseline.wrong_accepted[name]:
            found.append(
                f"{name}: {load[name].wrong_accepted} wrong values accepted without review, "
                f"above the baseline of {baseline.wrong_accepted[name]}"
            )
    found.extend(
        f"{name}: in the baseline but not scored"
        for name in baseline.fields
        if name not in accuracy
    )
    return found


def load_baseline(path: Path) -> Baseline:
    return Baseline.model_validate_json(path.read_text(encoding="utf-8"))


def save_baseline(path: Path, accuracy: Accuracy, load: Load) -> None:
    totals = {total for _, total in accuracy.values()}
    if len(totals) != 1:
        raise ValueError(f"fields were scored over different numbers of documents: {totals}")
    baseline = Baseline(
        documents=totals.pop(),
        fields={name: correct for name, (correct, _) in accuracy.items()},
        wrong_accepted={name: load[name].wrong_accepted for name in accuracy},
    )
    path.write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
