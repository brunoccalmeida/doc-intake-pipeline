"""``doc_intake.error_report``: the per-field error report of reviewed runs (#64)."""

from datetime import date
from decimal import Decimal

import pytest

from doc_intake.error_report import FieldErrors, error_report, upper_error_bound
from doc_intake.packs.receipt import RECEIPT
from doc_intake.review import Label


# Reference values from an independent implementation, SciPy 1.18.1, run once
# outside the project: beta.ppf(0.95, k + 1, n - k), which equals
# binomtest(k, n, alternative="less").proportion_ci(method="exact").high.
@pytest.mark.parametrize(
    ("errors", "reviewed", "bound"),
    [
        (0, 100, 0.02951304960703993),  # the rule of three: about 3/n
        (0, 300, 0.009936081944457708),  # a 1% ceiling takes about 300 clean fields
        (1, 100, 0.046559811453538935),
        (2, 1000, 0.006282284546723426),
        (5, 50, 0.19883300251641847),
        (3, 7, 0.7746784159675522),
        (0, 1, 0.95),
    ],
)
def test_the_upper_bound_is_the_exact_clopper_pearson_one(
    errors: int, reviewed: int, bound: float
) -> None:
    assert upper_error_bound(errors, reviewed) == pytest.approx(bound, rel=1e-9)


def test_the_bound_matches_nists_worked_example() -> None:
    # NIST/SEMATECH e-Handbook 7.2.4.1: N = 20, 4 defects, two-sided 90%, whose
    # upper limit solves P(X <= 4) = 0.05, the one-sided 95% bound used here.
    assert upper_error_bound(4, 20) == pytest.approx(0.401029, abs=1e-6)


def test_with_every_field_wrong_the_bound_is_one() -> None:
    assert upper_error_bound(4, 4) == 1.0


@pytest.mark.parametrize(("errors", "reviewed"), [(0, 0), (-1, 10), (11, 10)])
def test_counts_that_cannot_be_a_sample_fail(errors: int, reviewed: int) -> None:
    with pytest.raises(ValueError, match="reviewed"):
        upper_error_bound(errors, reviewed)


def text(file: str, field: str, suggested: object, truth: object) -> Label:
    verdict = "confirmed" if suggested == truth else "corrected"
    return Label(file, field, verdict, suggested, truth, source="text")


def test_fields_are_counted_per_field_and_source_in_schema_order() -> None:
    labels = [
        text("a.png", "total", Decimal("9.90"), Decimal("19.90")),
        text("a.png", "company", "ACME", "ACME"),
        Label("a.png", "company", "not_on_page", "ACME", None, source="image"),
        Label("a.png", "currency", "corrected", None, "MYR", source=None),
        text("b.png", "total", Decimal("5.00"), Decimal("5.00")),
        text("b.png", "company", "ACME", "ACME"),
        text("c.png", "company", "ACME", "ACMF"),
    ]

    assert error_report(labels, RECEIPT) == [
        FieldErrors("company", "text", reviewed=3, errors=1),
        FieldErrors("company", "image", reviewed=1, errors=1),
        FieldErrors("total", "text", reviewed=2, errors=1),
        FieldErrors("currency", "empty", reviewed=1, errors=1),
    ]


def test_an_error_is_a_value_the_reviewer_changed_not_a_verdict() -> None:
    labels = [
        # Absent and left empty: right, whatever the verdict says.
        Label("a.png", "currency", "not_on_page", None, None, source=None),
        Label("b.png", "currency", "confirmed", None, None, source=None),
        # The same amount, written another way: a money value, not its print (D15).
        Label("a.png", "total", "corrected", Decimal("9.9"), Decimal("9.90"), source="text"),
        Label("a.png", "date", "confirmed", date(2026, 3, 4), date(2026, 3, 4), source="text"),
    ]

    assert [(row.field, row.errors) for row in error_report(labels, RECEIPT)] == [
        ("date", 0),
        ("total", 0),
        ("currency", 0),
    ]


def test_a_row_gives_its_rate_and_bound() -> None:
    row = FieldErrors("total", "image", reviewed=50, errors=5)

    assert row.error_rate == 0.1
    assert row.upper_bound == pytest.approx(0.19883300251641847, rel=1e-9)


def test_no_reviewed_field_is_an_empty_report() -> None:
    assert error_report([], RECEIPT) == []


def test_a_field_the_pack_does_not_have_fails() -> None:
    labels = [text("a.png", "tip", "1", "1")]

    with pytest.raises(ValueError, match="tip"):
        error_report(labels, RECEIPT)
