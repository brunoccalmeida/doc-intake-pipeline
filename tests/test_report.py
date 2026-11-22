"""The Markdown eval report: gate verdict, accuracy per field, statuses, failures, cost.

It is published as the CI job summary, so it carries ids, field names and
outcomes only, never document content (AGENTS.md invariant 6, docs/DATA.md).
"""

from decimal import Decimal

from doc_intake.core.pricing import PRICE_SOURCES
from evals.baseline import Baseline
from evals.report import render_report
from evals.run import EvalRun, Usage
from evals.scoring import DocumentScore

USAGE = Usage(
    documents=3,
    calls=3,
    input_tokens=4_500,
    output_tokens=1_200,
    cost_usd=Decimal("0.042"),
    models=("claude-opus-5-5",),
)
RUN = EvalRun(
    scores=[
        DocumentScore(
            id="X1",
            status="ok",
            fields={"company": "correct", "total": "correct"},
            routes={"company": "accepted", "total": "accepted"},
        ),
        DocumentScore(
            id="X2",
            status="needs_review",
            fields={"company": "wrong", "total": "missing"},
            routes={"company": "review", "total": "empty"},
        ),
        DocumentScore(
            id="X3",
            status="failed",
            fields={"company": "document_failed", "total": "document_failed"},
            routes={"company": "review", "total": "review"},
            error="EmptyDocumentError",
        ),
    ],
    usage=USAGE,
)
BASELINE = Baseline(
    documents=3, fields={"company": 1, "total": 1}, wrong_accepted={"company": 0, "total": 0}
)


def test_passed_gate_is_stated_first() -> None:
    report = render_report(RUN, BASELINE, regressions=[])

    assert report.splitlines()[0].startswith("# Eval report")
    assert (
        "**Gate: passed.** No field scored below the baseline "
        "or accepted more wrong values than it." in report
    )


def test_review_load_per_field_and_in_total() -> None:
    # What a client asks: how many values arrive checked by nobody, how many
    # wait for a person, and how many wrong ones land in each group (#38).
    report = render_report(RUN, BASELINE, regressions=[])

    assert (
        "| Field | Accepted | Wrong accepted | Baseline | Sent to review "
        "| Wrong in review | Empty |" in report
    )
    assert "| company | 1 | 0 | 0 | 2 | 1 | 0 |" in report
    assert "| total | 1 | 0 | 0 | 1 | 0 | 1 |" in report
    assert "| **All fields** | 2 | 0 | 0 | 3 | 1 | 1 |" in report


def test_failed_gate_lists_each_regression() -> None:
    found = ["company: 0/3 correct, below the baseline of 1/3"]

    report = render_report(RUN, BASELINE, regressions=found)

    assert "**Gate: failed.**" in report
    assert "- company: 0/3 correct, below the baseline of 1/3" in report


def test_accuracy_per_field_with_its_baseline() -> None:
    report = render_report(RUN, BASELINE, regressions=[])

    assert "| company | 1/3 | 33.3% | 1/3 |" in report
    assert "| total | 1/3 | 33.3% | 1/3 |" in report


def test_status_counts() -> None:
    assert "| 1 | 1 | 1 |" in render_report(RUN, BASELINE, regressions=[])


def test_failures_by_document_and_field_with_a_failed_document_on_one_line() -> None:
    report = render_report(RUN, BASELINE, regressions=[])

    assert "| X2 | company | wrong |" in report
    assert "| X2 | total | missing |" in report
    assert "| X3 | all | document failed (EmptyDocumentError) |" in report
    assert "| X1 |" not in report


def test_usage_and_cost() -> None:
    report = render_report(RUN, BASELINE, regressions=[])

    assert "| Documents | Calls | Input tokens | Output tokens | Cost (USD) " in report
    assert "| Average per document (USD) | Models |" in report
    assert "| 3 | 3 | 4500 | 1200 | $0.042 | $0.014000 | claude-opus-5-5 |" in report


def test_each_price_source_is_cited_with_the_date_it_was_checked() -> None:
    report = render_report(RUN, BASELINE, regressions=[])

    for url, checked_on in PRICE_SOURCES.items():
        assert f"{url} (checked on {checked_on})" in report


def test_no_baseline_yet_is_said_instead_of_a_column_of_blanks() -> None:
    report = render_report(RUN, None, regressions=[])

    assert "| company | 1/3 | 33.3% | none |" in report
    assert "| company | 1 | 0 | none | 2 | 1 | 0 |" in report
    assert "| **All fields** | 2 | 0 | none | 3 | 1 | 1 |" in report
