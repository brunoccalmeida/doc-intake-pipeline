"""The README's eval summary: written from an eval run, never typed by hand (#40).

The README quotes the eval to clients; a re-recording or a price change would
leave those numbers stale in silence. The eval rewrites the block between its
markers (``--update-readme``) and fails when the committed one differs.
"""

from decimal import Decimal

import pytest

from evals.readme import END, START, ReadmeMarkerError, render_summary, replace_summary
from evals.run import EvalRun, Usage
from evals.scoring import DocumentScore

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
            fields={"company": "wrong", "total": "correct"},
            routes={"company": "review", "total": "empty"},
        ),
        DocumentScore(
            id="X3",
            status="ok",
            fields={"company": "unexpected", "total": "correct"},
            routes={"company": "accepted", "total": "review"},
        ),
    ],
    usage=Usage(
        documents=3,
        calls=3,
        input_tokens=4_500,
        output_tokens=1_200,
        cost_usd=Decimal("0.094"),
        models=("claude-opus-5-5",),
    ),
)


def test_the_summary_counts_values_and_where_they_went() -> None:
    summary = render_summary(RUN)

    assert summary.splitlines() == [
        "Measured on 3 public scanned receipts, 6 values in all (company, total):",
        "",
        "- **4 of 6 correct.**",
        "- **3 accepted automatically**, 1 of them wrong.",
        "- **2 sent to a person to check**, 1 of them wrong.",
        "- **1 left empty**, with the reason.",
        "- **$0.09 for the whole set**, about $0.03 per receipt.",
    ]


def test_no_wrong_value_reads_as_none() -> None:
    run = EvalRun(scores=RUN.scores[:1], usage=RUN.usage)

    assert "- **2 accepted automatically**, none of them wrong." in render_summary(run)


def test_a_cost_below_a_cent_is_not_shown_as_zero() -> None:
    # A cheaper model (about $0.0005 a receipt) would round to "$0.00": free, which it is not.
    usage = Usage(
        documents=3,
        calls=3,
        input_tokens=4_500,
        output_tokens=1_200,
        cost_usd=Decimal("0.0015"),
        models=("gpt-6-luna",),
    )

    summary = render_summary(EvalRun(scores=RUN.scores, usage=usage))

    assert summary.splitlines()[-1] == (
        "- **under $0.01 for the whole set**, under $0.01 per receipt."
    )


def test_the_block_between_the_markers_is_replaced_and_the_rest_kept() -> None:
    readme = f"# Title\n\nBefore.\n\n{START}\nold numbers\n{END}\n\nAfter.\n"

    assert replace_summary(readme, "new numbers") == (
        f"# Title\n\nBefore.\n\n{START}\nnew numbers\n{END}\n\nAfter.\n"
    )


@pytest.mark.parametrize(
    "readme",
    [
        "no markers at all\n",
        f"{START}\nonly the start\n",
        f"{END}\n{START}\nin the wrong order\n",
        f"{START}\none\n{END}\n{START}\ntwo\n{END}\n",
    ],
)
def test_missing_or_repeated_markers_fail_naming_them(readme: str) -> None:
    with pytest.raises(ReadmeMarkerError, match="eval-summary:start"):
        replace_summary(readme, "numbers")
