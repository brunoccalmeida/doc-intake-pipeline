"""``doc_intake.acceptance``: per-field auto-acceptance of image-read values (#65)."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from doc_intake.acceptance import (
    DEFAULT_AUDIT_RATE,
    AcceptancePolicy,
    FieldEvidence,
    accepted_fields,
    anytime_upper_bound,
    audit,
    calibrate,
)
from doc_intake.core.result import ExtractionResult
from doc_intake.packs.receipt import RECEIPT, Receipt
from doc_intake.review import Label


# Reference values from an independent implementation run once outside the
# project, SciPy 1.18.1: the upper root of S*log(p) + (n-S)*log1p(-p) equal to
# betaln(1+S, b+n-S) - betaln(1, b) + log(delta), with b = (1-target)/target,
# found by scipy.optimize.brentq.
@pytest.mark.parametrize(
    ("errors", "reviewed", "target", "delta", "bound"),
    [
        (0, 330, 0.02, 0.01, 0.019952461951938442),  # the first clean n under 2%
        (0, 329, 0.02, 0.01, 0.02000462706662144),  # one label short
        (3, 500, 0.02, 0.01, 0.02625561741120792),
        (1, 50, 0.05, 0.01, 0.15495151393419068),
        (0, 1, 0.02, 0.01, 0.9902),
        (2, 1000, 0.01, 0.05, 0.009338965916096084),
        (10, 40, 0.02, 0.01, 0.6283416087631815),
    ],
)
def test_the_anytime_bound_matches_an_independent_implementation(
    errors: int, reviewed: int, target: float, delta: float, bound: float
) -> None:
    assert anytime_upper_bound(errors, reviewed, target=target, delta=delta) == pytest.approx(
        bound, rel=1e-9
    )


def test_with_every_field_wrong_or_none_reviewed_nothing_is_ruled_out() -> None:
    assert anytime_upper_bound(7, 7, target=0.02, delta=0.01) == 1.0
    assert anytime_upper_bound(0, 0, target=0.02, delta=0.01) == 1.0


@pytest.mark.parametrize(("errors", "reviewed"), [(-1, 10), (11, 10)])
def test_counts_that_cannot_be_a_sample_fail(errors: int, reviewed: int) -> None:
    with pytest.raises(ValueError, match="reviewed"):
        anytime_upper_bound(errors, reviewed, target=0.02, delta=0.01)


def policy(**evidence: tuple[int, int]) -> AcceptancePolicy:
    return AcceptancePolicy(
        pack="receipt",
        target=0.02,
        evidence={name: FieldEvidence(reviewed=n, errors=k) for name, (n, k) in evidence.items()},
        runs=["2026-11-22T15-30-00Z"],
    )


def test_a_field_is_accepted_only_when_its_bound_with_every_field_tested_is_under_target() -> None:
    # Five receipt fields share the 5% error budget: each is tested at 1%
    # (Bonferroni), where 330 clean labels are the first to pass 2%.
    assert accepted_fields(
        policy(total=(330, 0), date=(329, 0), company=(10_000, 300)), RECEIPT
    ) == {"total"}


def test_the_policy_defaults_to_95_percent_and_a_ten_percent_audit() -> None:
    assert policy().confidence == 0.95
    assert policy().audit_rate == DEFAULT_AUDIT_RATE == 0.10


@pytest.mark.parametrize(
    "change",
    [
        {"target": 0.0},
        {"target": 1.0},
        {"confidence": 1.0},
        {"audit_rate": 0.0},  # an accepted field nobody measures any more
        {"audit_rate": 1.5},
        {"evidence": {"total": {"reviewed": 3, "errors": 4}}},
        {"evidence": {"total": {"reviewed": 3, "errors": 0, "accepted": True}}},
    ],
)
def test_a_policy_that_cannot_hold_fails_to_load(change: dict[str, object]) -> None:
    data = policy().model_dump() | change
    with pytest.raises(ValidationError):
        AcceptancePolicy.model_validate(data)


def test_a_policy_for_another_pack_or_field_fails() -> None:
    with pytest.raises(ValueError, match="invoice"):
        accepted_fields(policy().model_copy(update={"pack": "invoice"}), RECEIPT)
    with pytest.raises(ValueError, match="vendor"):
        accepted_fields(policy(vendor=(400, 0)), RECEIPT)


def image(file: str, field: str, suggested: object, truth: object) -> Label:
    verdict = "confirmed" if suggested == truth else "corrected"
    return Label(file, field, verdict, suggested, truth, source="image", queued=True)


def test_calibration_counts_image_read_labels_of_every_field() -> None:
    labels = [
        image("a.png", "total", Decimal("9.90"), Decimal("9.90")),
        image("b.png", "total", Decimal("5.00"), Decimal("15.00")),
        image("a.png", "date", date(2026, 3, 4), date(2026, 3, 4)),
        # An accepted value the reviewer chose to check, outside the audit
        # draw: a pick, not a sample, so it would bias the count.
        Label("d.png", "total", "confirmed", Decimal("2.00"), Decimal("2.00"), source="image"),
        # Read from the text or left empty: another population, not calibrated.
        Label("c.png", "total", "confirmed", Decimal("1.00"), Decimal("1.00"), source="text"),
        Label("c.png", "currency", "not_on_page", None, None, source=None),
    ]

    calibrated = calibrate(labels, RECEIPT, target=0.05, runs=["r1", "r2"])

    assert calibrated == AcceptancePolicy(
        pack="receipt",
        target=0.05,
        evidence={
            "company": FieldEvidence(reviewed=0, errors=0),
            "address": FieldEvidence(reviewed=0, errors=0),
            "date": FieldEvidence(reviewed=1, errors=0),
            "total": FieldEvidence(reviewed=2, errors=1),
            "currency": FieldEvidence(reviewed=0, errors=0),
        },
        runs=["r1", "r2"],
    )


def cited(value: str, source: str = "image") -> dict[str, object]:
    return {
        "value": value,
        "citation": {"page": 1, "source": source, "quote": value},
        "reason": None,
    }


def receipt_result(*, review: list[str]) -> ExtractionResult[Receipt]:
    fields = Receipt.model_validate(
        {
            "company": cited("ACME"),
            "address": cited("1 Main St", source="text"),
            "date": cited("2026-03-04"),
            "total": cited("9.90"),
            "currency": {"value": None, "citation": None, "reason": "not printed"},
        }
    )
    if not review:
        return ExtractionResult[Receipt](status="ok", fields=fields)
    errors = [f"{name}: read from the image of page 1; check it on the page" for name in review]
    return ExtractionResult[Receipt](
        status="needs_review", fields=fields, errors=errors, review=review
    )


def draws(*values: float) -> Iterator[float]:
    return iter(values)


def test_an_audit_sends_a_drawn_share_of_accepted_image_fields_back_in_schema_order() -> None:
    # total and date were accepted from the image; company is under review anyway.
    result = receipt_result(review=["company"])
    drawn = draws(0.05, 0.50)  # date drawn under the rate, total not

    audited = audit(result, frozenset({"date", "total", "address"}), rate=0.10, draw=drawn.__next__)

    assert audited.status == "needs_review"
    assert audited.review == ["company", "date"]
    assert audited.errors[-1] == (
        "date: audit sample of values accepted from the image; check it on page 1"
    )
    assert next(drawn, None) is None  # one draw per accepted image field, no more


def test_an_audit_of_an_ok_result_makes_it_need_review() -> None:
    audited = audit(receipt_result(review=[]), frozenset({"total"}), rate=0.10, draw=lambda: 0.0)

    assert (audited.status, audited.review) == ("needs_review", ["total"])


def test_nothing_drawn_leaves_the_result_as_it_was() -> None:
    result = receipt_result(review=[])

    assert audit(result, frozenset({"total", "date"}), rate=0.10, draw=lambda: 0.10) is result
