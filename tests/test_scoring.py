"""Eval scoring: per-field outcome against the golden record, and accuracy per field.

The rules (``docs/ARCHITECTURE.md`` D4, ``evals/scoring.py``): text matches
after folding case and collapsing whitespace, like SROIE's exact match on its
all-uppercase ground truth; dates and money match by value. An empty field
and a value disagree in both directions, and a document that failed scores
nothing, not even an expected empty field.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.result import Citation, ExtractedField, ExtractionResult
from evals.scoring import (
    DocumentScore,
    ReviewLoad,
    field_accuracy,
    field_outcome,
    review_load,
    score_document,
    status_counts,
)
from packs.receipt import Receipt


def cited[T](value: T) -> ExtractedField[T]:
    return ExtractedField[T](
        value=value, citation=Citation(page=1, source="text", quote="q"), reason=None
    )


def empty() -> ExtractedField[str]:
    return ExtractedField[str](value=None, citation=None, reason="not printed")


def receipt(
    company: str = "ACME TRADING SDN BHD",
    total: str = "9.00",
    currency: ExtractedField[str] | None = None,
) -> Receipt:
    return Receipt(
        company=cited(company),
        address=cited("NO. 12, JALAN MAJU, 43300 SERI KEMBANGAN"),
        date=cited(date(2018, 1, 15)),
        total=cited(Decimal(total)),
        currency=currency if currency is not None else cited("MYR"),
    )


@pytest.mark.parametrize(
    ("expected", "predicted"),
    [
        ("ACME TRADING SDN BHD", "Acme Trading Sdn Bhd"),
        ("NO. 12, JALAN MAJU", "NO. 12,\nJALAN   MAJU"),
        ("ACME", " ACME "),
        ("JOHOR BAHRU,JOHOR", "Johor Bahru, Johor"),
        ("NO 19-G& 19-1& 19-2", "NO 19-G&19-1&19-2"),
        ("NO.5 & 7 , JALAN", "NO.5 & 7, JALAN"),
    ],
    ids=[
        "case",
        "inner-whitespace",
        "outer-whitespace",
        "space-after-comma",
        "space-after-ampersand",
        "space-before-comma",
    ],
)
def test_text_matches_after_folding_case_and_whitespace(expected: str, predicted: str) -> None:
    assert field_outcome(cited(expected), cited(predicted)) == "correct"


@pytest.mark.parametrize(
    ("expected", "predicted"),
    [
        ("ACME TRADING SDN BHD", "ACME TRADING SDN. BHD"),
        ("ACME TRADING", "ACME TRADING SDN BHD"),
        ("LOT PTD 101051 JALAN PERMAS", "LOT PTD 101051, JALAN PERMAS"),
        ("JALAN MAJU", "JALANMAJU"),
    ],
    ids=["punctuation", "extra-words", "extra-comma", "merged-words"],
)
def test_text_differing_beyond_case_and_whitespace_is_wrong(expected: str, predicted: str) -> None:
    assert field_outcome(cited(expected), cited(predicted)) == "wrong"


def test_money_matches_by_value_not_by_digits() -> None:
    assert field_outcome(cited(Decimal("9.00")), cited(Decimal("9.0"))) == "correct"
    assert field_outcome(cited(Decimal("9.00")), cited(Decimal("9.01"))) == "wrong"


def test_date_matches_by_value() -> None:
    assert field_outcome(cited(date(2018, 1, 15)), cited(date(2018, 1, 15))) == "correct"
    assert field_outcome(cited(date(2018, 1, 15)), cited(date(2018, 1, 16))) == "wrong"


def test_empty_where_a_value_is_expected_is_missing() -> None:
    assert field_outcome(cited("MYR"), empty()) == "missing"


def test_value_where_empty_is_expected_is_unexpected() -> None:
    assert field_outcome(empty(), cited("MYR")) == "unexpected"


def test_empty_where_empty_is_expected_is_correct_whatever_the_reason() -> None:
    other_reason = ExtractedField[str](value=None, citation=None, reason="'$' is ambiguous")
    assert field_outcome(empty(), other_reason) == "correct"


def test_a_document_that_failed_scores_every_field_as_failed() -> None:
    golden = receipt(currency=empty())
    result = ExtractionResult[Receipt](status="failed", errors=["company: Field required"])

    score = score_document("X1", golden, result)

    assert score.status == "failed"
    assert set(score.fields.values()) == {"document_failed"}
    assert list(score.fields) == list(Receipt.model_fields)


def test_a_document_that_could_not_be_read_is_failed_and_names_the_error() -> None:
    score = score_document("X1", receipt(), "EmptyDocumentError")

    assert score.status == "failed"
    assert score.error == "EmptyDocumentError"
    assert set(score.fields.values()) == {"document_failed"}


def test_needs_review_is_scored_on_its_fields() -> None:
    result = ExtractionResult[Receipt](
        status="needs_review",
        fields=receipt(total="9.50"),
        errors=["total: quote not found"],
        review=["total"],
    )

    score = score_document("X1", receipt(), result)

    assert score.status == "needs_review"
    assert score.fields["total"] == "wrong"
    assert score.fields["company"] == "correct"


def test_each_field_is_routed_to_review_accepted_or_empty() -> None:
    # Review is per field (D12): the fields the result names go to a person,
    # the other values are accepted, and an empty field has no value to accept.
    result = ExtractionResult[Receipt](
        status="needs_review",
        fields=receipt(currency=empty()),
        errors=["total: quote not found"],
        review=["total"],
    )

    score = score_document("X1", receipt(), result)

    assert score.routes == {
        "company": "accepted",
        "address": "accepted",
        "date": "accepted",
        "total": "review",
        "currency": "empty",
    }


@pytest.mark.parametrize(
    "result",
    [ExtractionResult[Receipt](status="failed", errors=["invalid JSON"]), "EmptyDocumentError"],
    ids=["no-valid-answer", "unreadable"],
)
def test_every_field_of_a_failed_document_goes_to_review(
    result: ExtractionResult[Receipt] | str,
) -> None:
    # A failure is handed to a person whole (invariant 2), never accepted.
    score = score_document("X1", receipt(), result)

    assert set(score.routes.values()) == {"review"}
    assert list(score.routes) == list(Receipt.model_fields)


def test_routes_must_cover_the_same_fields_as_outcomes() -> None:
    with pytest.raises(ValidationError, match="routes and outcomes name different fields"):
        DocumentScore(id="X1", status="ok", fields={"total": "correct"}, routes={})


def test_review_load_counts_wrong_values_where_they_land() -> None:
    # "wrong" and "unexpected" are values that should not reach a client; a
    # missing value is empty, not a value, and the accuracy gate already counts it.
    golden = receipt(currency=empty())
    accepted_wrong = ExtractionResult[Receipt](
        status="ok", fields=receipt(company="OTHER", currency=cited("MYR"))
    )
    reviewed_wrong = ExtractionResult[Receipt](
        status="needs_review",
        fields=receipt(total="9.50", currency=empty()),
        errors=["total: quote not found"],
        review=["total"],
    )
    scores = [
        score_document("X1", golden, accepted_wrong),
        score_document("X2", golden, reviewed_wrong),
        score_document("X3", golden, "EmptyDocumentError"),
    ]

    load = review_load(scores)

    assert load["company"] == ReviewLoad(accepted=2, review=1, empty=0, wrong_accepted=1)
    assert load["total"] == ReviewLoad(accepted=1, review=2, empty=0, wrong_review=1)
    assert load["currency"] == ReviewLoad(accepted=1, review=1, empty=1, wrong_accepted=1)


def test_review_load_total_sums_every_field() -> None:
    load = {
        "company": ReviewLoad(accepted=2, review=1, empty=0, wrong_accepted=1),
        "total": ReviewLoad(accepted=1, review=2, empty=0, wrong_review=1),
    }

    assert ReviewLoad.total(load.values()) == ReviewLoad(
        accepted=3, review=3, empty=0, wrong_accepted=1, wrong_review=1
    )


def test_field_accuracy_counts_correct_over_documents() -> None:
    scores = [
        score_document("X1", receipt(), ExtractionResult[Receipt](status="ok", fields=receipt())),
        score_document(
            "X2",
            receipt(),
            ExtractionResult[Receipt](status="ok", fields=receipt(company="OTHER")),
        ),
        score_document("X3", receipt(), "EmptyDocumentError"),
    ]

    accuracy = field_accuracy(scores)

    assert accuracy["company"] == (1, 3)
    assert accuracy["total"] == (2, 3)


def test_status_counts_cover_every_status_even_when_zero() -> None:
    scores = [
        DocumentScore(id="X1", status="ok", fields={}, routes={}),
        DocumentScore(id="X2", status="failed", fields={}, routes={}, error="EmptyDocumentError"),
    ]

    assert status_counts(scores) == {"ok": 1, "needs_review": 0, "failed": 1}
