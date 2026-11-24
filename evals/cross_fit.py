"""Auto-acceptance in the eval, each receipt left out of its own policy (#65, D22).

A client calibrates on receipts it reviewed and applies the policy to new
ones. The eval plays both parts with the golden set: for each receipt, a
policy calibrated on every *other* receipt (leave-one-out cross-fitting), with
the golden records as the reviewer's labels, decides which of its image-read
fields are accepted. A receipt never calibrates its own acceptance, so a
wrong value cannot vouch for itself.

The receipts where a policy accepts something are scored again with it
(``evals.run.run_eval``'s ``accept``), and every wrong value it lets through
fails the gate: nothing invented reaches a client unchecked (invariant 1),
so the limit is zero, not a baseline.

A label is wrong when the field's outcome is not ``correct`` (the eval's
comparison, D4). Counts, field names and rates only (invariant 6).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from doc_intake.acceptance import (
    CONFIDENCE,
    AcceptancePolicy,
    FieldEvidence,
    accepted_fields,
    anytime_upper_bound,
)
from doc_intake.core.extract import Pack
from evals.scoring import DocumentScore

# A client's target in the eval: own judgment, the example of the docs (D22).
EVAL_TARGET = 0.02
_WRONG = frozenset({"wrong", "unexpected"})


@dataclass(frozen=True, slots=True)
class CrossFit:
    """The golden set's image-read evidence and what each receipt's policy accepts.

    ``evidence`` covers every field of the pack, over all receipts;
    ``accepts`` maps a receipt to its accepted image-read fields, and leaves
    out receipts with none.
    """

    target: float
    evidence: dict[str, FieldEvidence]
    accepts: dict[str, frozenset[str]]

    def wrong_accepted(self, rescored: Iterable[DocumentScore]) -> dict[str, int]:
        """Per field accepted anywhere, the wrong values its policies let through."""
        accepted = {name for fields in self.accepts.values() for name in fields}
        # In schema order: the evidence covers every field of the pack in it.
        wrong = {name: 0 for name in self.evidence if name in accepted}
        for score in rescored:
            for name in self.accepts.get(score.id, frozenset()):
                if score.routes[name] == "accepted" and score.fields[name] in _WRONG:
                    wrong[name] += 1
        return wrong


def cross_fit[S: BaseModel](
    scores: Sequence[DocumentScore],
    from_image: Mapping[str, frozenset[str]],
    pack: Pack[S],
    *,
    target: float = EVAL_TARGET,
) -> CrossFit:
    """Leave-one-out policies over ``scores``; ``from_image``: image-read fields per receipt."""
    fields = list(pack.schema.model_fields)
    labels = [
        (score.id, name, score.fields[name] != "correct")
        for score in scores
        for name in from_image.get(score.id, frozenset())
    ]
    accepts: dict[str, frozenset[str]] = {}
    for score in scores:
        others = [(name, wrong) for document, name, wrong in labels if document != score.id]
        policy = AcceptancePolicy(
            pack=pack.name,
            target=target,
            evidence=_evidence(others, fields),
            runs=["golden set without " + score.id],
        )
        accepted = accepted_fields(policy, pack) & from_image.get(score.id, frozenset())
        if accepted:
            accepts[score.id] = accepted
    every = [(name, wrong) for _, name, wrong in labels]
    return CrossFit(target=target, evidence=_evidence(every, fields), accepts=accepts)


def _evidence(labels: Iterable[tuple[str, bool]], fields: list[str]) -> dict[str, FieldEvidence]:
    reviewed = dict.fromkeys(fields, 0)
    errors = dict.fromkeys(fields, 0)
    for name, wrong in labels:
        reviewed[name] += 1
        errors[name] += wrong
    return {name: FieldEvidence(reviewed=reviewed[name], errors=errors[name]) for name in fields}


def render_cross_fit(fit: CrossFit, *, wrong: Mapping[str, int]) -> list[str]:
    """The report's section: per field, the evidence, its bound and what was accepted."""
    delta = (1 - CONFIDENCE) / len(fit.evidence)
    lines = [
        "## Auto-acceptance, cross-fitted",
        "",
        f"Each receipt gets the policy calibrated on the other receipts at a target of "
        f"{fit.target:.0%} (D22); any wrong value it accepts fails the gate. The bound is "
        "over every receipt's image-read values, at the confidence each field gets.",
        "",
        "| Field | Image-read values | Wrong | Upper bound | Receipts accepted | Wrong accepted |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, evidence in fit.evidence.items():
        bound = anytime_upper_bound(
            evidence.errors, evidence.reviewed, target=fit.target, delta=delta
        )
        accepted = sum(name in fields for fields in fit.accepts.values())
        lines.append(
            f"| {name} | {evidence.reviewed} | {evidence.errors} | {bound:.3%} "
            f"| {accepted} | {wrong.get(name, 0)} |"
        )
    return lines
