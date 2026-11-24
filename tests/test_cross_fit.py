"""``evals.cross_fit``: auto-acceptance in the eval, each receipt left out of its own policy."""

from doc_intake.acceptance import FieldEvidence
from doc_intake.packs.receipt import RECEIPT
from evals.cross_fit import CrossFit, cross_fit, render_cross_fit
from evals.scoring import DocumentScore, FieldOutcome, FieldRoute

FIELDS = list(RECEIPT.schema.model_fields)


def score(document_id: str, **outcomes: FieldOutcome) -> DocumentScore:
    fields: dict[str, FieldOutcome] = {name: outcomes.get(name, "correct") for name in FIELDS}
    routes: dict[str, FieldRoute] = dict.fromkeys(FIELDS, "accepted")
    return DocumentScore(id=document_id, status="ok", fields=fields, routes=routes)


def test_each_receipt_gets_the_fields_a_policy_of_the_other_receipts_accepts() -> None:
    # 341 receipts with the total read from the image, one of them wrong:
    # left out, the wrong one sees 340 clean totals (accepted at 2%); every
    # other one sees 339 clean and the wrong one, which keeps total in review.
    scores = [score(f"r{i}") for i in range(340)] + [score("bad", total="wrong")]
    from_image = {s.id: frozenset({"total"}) for s in scores}
    from_image["r0"] = frozenset({"total", "date"})  # one date: far from enough

    fit = cross_fit(scores, from_image, RECEIPT, target=0.02)

    assert fit.accepts == {"bad": frozenset({"total"})}
    assert fit.evidence["total"] == FieldEvidence(reviewed=341, errors=1)
    assert fit.evidence["date"] == FieldEvidence(reviewed=1, errors=0)


def test_a_field_not_read_from_the_image_of_a_receipt_is_not_accepted_there() -> None:
    scores = [score(f"r{i}") for i in range(341)]
    from_image = {s.id: frozenset({"total"}) for s in scores}
    from_image["r0"] = frozenset()

    fit = cross_fit(scores, from_image, RECEIPT, target=0.02)

    assert "r0" not in fit.accepts
    assert len(fit.accepts) == 340


def test_wrong_values_auto_accepted_are_counted_per_field_from_the_rescored_run() -> None:
    fit = CrossFit(
        target=0.02,
        evidence={name: FieldEvidence(reviewed=0, errors=0) for name in FIELDS},
        accepts={"a": frozenset({"total", "date"}), "b": frozenset({"total"})},
    )
    rescored = [
        score("a", total="wrong"),
        score("b", total="unexpected"),
        # Routed to review for another reason: not auto-accepted.
        DocumentScore(
            id="c",
            status="needs_review",
            fields=dict.fromkeys(FIELDS, "wrong"),
            routes=dict.fromkeys(FIELDS, "review"),
        ),
    ]

    assert fit.wrong_accepted(rescored) == {"date": 0, "total": 2}


def test_the_section_shows_evidence_bounds_and_wrong_accepted_without_values() -> None:
    fit = CrossFit(
        target=0.02,
        evidence={name: FieldEvidence(reviewed=0, errors=0) for name in FIELDS}
        | {"address": FieldEvidence(reviewed=9, errors=1)},
        accepts={},
    )

    lines = render_cross_fit(fit, wrong={})

    assert lines[0] == "## Auto-acceptance, cross-fitted"
    # Bound from the SciPy reference of tests/test_acceptance.py.
    assert "| address | 9 | 1 | 64.941% | 0 | 0 |" in lines
    assert "| total | 0 | 0 | 100.000% | 0 | 0 |" in lines
