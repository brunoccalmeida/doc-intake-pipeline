"""The eval gate: no field may score below the committed baseline, nor accept more wrong values.

Replay is deterministic (the same recordings give the same scores), so the
tolerance is zero: any drop is a real change, not noise.
"""

from pathlib import Path

from evals.baseline import Baseline, load_baseline, regressions, save_baseline
from evals.scoring import ReviewLoad

BASELINE = Baseline(
    documents=20, fields={"company": 15, "total": 18}, wrong_accepted={"company": 0, "total": 1}
)
ACCURACY = {"company": (15, 20), "total": (18, 20)}


def load(wrong_accepted: int = 0) -> ReviewLoad:
    return ReviewLoad(accepted=10, review=9, empty=1, wrong_accepted=wrong_accepted)


LOAD = {"company": load(0), "total": load(1)}


def test_equal_or_better_passes() -> None:
    better = {"company": load(0), "total": load(0)}
    assert regressions({"company": (15, 20), "total": (19, 20)}, better, BASELINE) == []


def test_one_correct_fewer_fails_naming_the_field_and_both_scores() -> None:
    found = regressions({"company": (14, 20), "total": (18, 20)}, LOAD, BASELINE)

    assert found == ["company: 14/20 correct, below the baseline of 15/20"]


def test_one_more_wrong_value_accepted_fails_even_with_accuracy_unchanged() -> None:
    # A value that moves from review to accepted keeps its accuracy: only this
    # count sees a wrong value now reaching a client unchecked (#38).
    found = regressions(ACCURACY, {"company": load(1), "total": load(1)}, BASELINE)

    assert found == ["company: 1 wrong values accepted without review, above the baseline of 0"]


def test_a_field_without_a_baseline_fails() -> None:
    found = regressions({**ACCURACY, "date": (20, 20)}, {**LOAD, "date": load(0)}, BASELINE)

    assert found == ["date: no baseline; record one with 'uv run poe eval --update-baseline'"]


def test_a_field_without_a_wrong_accepted_baseline_fails() -> None:
    partial = BASELINE.model_copy(update={"wrong_accepted": {"company": 0}})

    found = regressions(ACCURACY, LOAD, partial)

    assert found == [
        "total: no baseline of wrong accepted values; "
        "record one with 'uv run poe eval --update-baseline'"
    ]


def test_a_baseline_field_no_longer_scored_fails() -> None:
    found = regressions({"company": (15, 20)}, {"company": load(0)}, BASELINE)

    assert found == ["total: in the baseline but not scored"]


def test_a_different_number_of_documents_fails() -> None:
    found = regressions({"company": (15, 19), "total": (18, 19)}, LOAD, BASELINE)

    assert found == ["the eval scored 19 documents, the baseline 20"]


def test_baseline_round_trips_through_its_file(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"

    save_baseline(path, ACCURACY, LOAD)

    assert load_baseline(path) == BASELINE
