"""The eval gate: no field may score below the committed baseline.

Replay is deterministic (the same recordings give the same scores), so the
tolerance is zero: any drop is a real change, not noise.
"""

from pathlib import Path

from evals.baseline import Baseline, load_baseline, regressions, save_baseline

BASELINE = Baseline(documents=20, fields={"company": 15, "total": 18})


def test_equal_or_better_passes() -> None:
    assert regressions({"company": (15, 20), "total": (19, 20)}, BASELINE) == []


def test_one_correct_fewer_fails_naming_the_field_and_both_scores() -> None:
    found = regressions({"company": (14, 20), "total": (18, 20)}, BASELINE)

    assert found == ["company: 14/20 correct, below the baseline of 15/20"]


def test_a_field_without_a_baseline_fails() -> None:
    found = regressions({"company": (15, 20), "total": (18, 20), "date": (20, 20)}, BASELINE)

    assert found == ["date: no baseline; record one with 'uv run poe eval --update-baseline'"]


def test_a_baseline_field_no_longer_scored_fails() -> None:
    found = regressions({"company": (15, 20)}, BASELINE)

    assert found == ["total: in the baseline but not scored"]


def test_a_different_number_of_documents_fails() -> None:
    found = regressions({"company": (15, 19), "total": (18, 19)}, BASELINE)

    assert found == ["the eval scored 19 documents, the baseline 20"]


def test_baseline_round_trips_through_its_file(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"

    save_baseline(path, {"company": (15, 20), "total": (18, 20)})

    assert load_baseline(path) == BASELINE
