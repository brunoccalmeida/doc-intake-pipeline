"""Per-field auto-acceptance of image-read values (#65, docs/ARCHITECTURE.md D22).

By default every value read from the page image goes to review (D12, D14).
A client may turn that off field by field, with an acceptance policy: a file
holding a target error rate and, per field, the image-read values reviewers
checked and how many were wrong (``calibrate``, from reviewed run folders).

A field is accepted when the error rate those labels still allow is under the
target (``accepted_fields``). Two choices make that claim hold:

- **The bound stays valid however often it is looked at.** A client re-runs
  the calibration as labels accumulate, until a field passes; a fixed-sample
  bound (Clopper-Pearson) checked that way passes a bad field far more often
  than its level says. ``anytime_upper_bound`` is a confidence sequence: the
  prior-posterior ratio of a Beta prior, a nonnegative martingale starting at
  1 (Waudby-Smith and Ramdas, 2020, Prop. 2.1), which by Ville's inequality
  exceeds ``1/delta`` at any time with probability at most ``delta``.
- **Several fields share the error budget.** Every field of the pack is a
  hypothesis ("its error rate is above the target"), so each is tested at
  ``delta / fields`` (Bonferroni), the family-wise control of Learn then Test
  (Angelopoulos et al., 2021): the chance that any accepted field is above the
  target stays under ``1 - confidence``.

Once a field is accepted no one reviews it, so ``audit`` sends a random share
of its accepted values back to review; those labels keep measuring it, and
the next calibration turns the field off if they push its bound up.

The policy holds the evidence, never an "accepted" flag: whether a field is
accepted is always recomputed from its counts, so a policy cannot claim more
than its labels show.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import BaseModel, Field, model_validator

from doc_intake.core.extract import Pack
from doc_intake.core.result import ExtractionResult, StrictModel, is_field

if TYPE_CHECKING:
    # doc_intake.review imports doc_intake.batch, which imports this module;
    # annotations are evaluated lazily (PEP 649), so typing needs no import.
    from doc_intake.review import Label

CONFIDENCE = 0.95
# Own judgment, docs/ARCHITECTURE.md D22: no source gives a method; Appian's
# guidance is 5-10% once running, AWS A2I's examples sample 5%.
DEFAULT_AUDIT_RATE = 0.10

type Rate = Annotated[float, Field(gt=0, lt=1)]


class FieldEvidence(StrictModel, frozen=True):
    """Image-read values of one field that reviewers checked, and the wrong ones."""

    reviewed: Annotated[int, Field(ge=0)]
    errors: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _errors_within_reviewed(self) -> Self:
        if self.errors > self.reviewed:
            raise ValueError("more errors than reviewed values")
        return self


class AcceptancePolicy(StrictModel, frozen=True):
    """A client's acceptance policy: the target and the evidence per field.

    ``runs`` names the reviewed run folders the evidence came from.
    """

    pack: str
    target: Rate
    confidence: Rate = CONFIDENCE
    audit_rate: Annotated[float, Field(gt=0, le=1)] = DEFAULT_AUDIT_RATE
    evidence: dict[str, FieldEvidence]
    runs: list[str]


@dataclass(frozen=True, slots=True)
class Acceptance:
    """What a run applies: the accepted fields and the audit of their values.

    ``draw`` returns a uniform number in [0, 1) per accepted value; a run uses
    ``random.SystemRandom().random``, a test a scripted sequence.
    """

    fields: frozenset[str]
    audit_rate: float
    draw: Callable[[], float]


def load_policy(path: Path) -> AcceptancePolicy:
    """The policy in ``path``; a missing or invalid file raises before any document is read."""
    return AcceptancePolicy.model_validate_json(path.read_text(encoding="utf-8"))


def anytime_upper_bound(errors: int, reviewed: int, *, target: float, delta: float) -> float:
    """The upper end of a confidence sequence for an error rate, at level ``delta``.

    With a Beta(1, b) prior on the rate ``p``, the prior-posterior ratio after
    ``errors`` wrong values in ``reviewed`` is

        M(p) = B(1 + errors, b + reviewed - errors) / B(1, b) / L(p),
        L(p) = p ** errors * (1 - p) ** (reviewed - errors),

    and the rates it has not ruled out are those with ``M(p) < 1 / delta``.
    ``L`` is log-concave, so they form an interval; its upper end is returned.
    The prior's mean is the target (``b = (1 - target) / target``): fixed
    before any label, as validity requires, and centred where the decision is
    close. With no value reviewed, or every value wrong, the bound is 1.
    """
    if not 0 <= errors <= reviewed:
        raise ValueError(f"{errors} errors in {reviewed} reviewed values is not a sample")
    if reviewed == 0 or errors == reviewed:
        return 1.0
    b = (1 - target) / target
    # M(p) < 1/delta  <=>  log L(p) > log B(1+S, b+n-S) - log B(1, b) + log delta
    floor = _log_beta(1 + errors, b + reviewed - errors) - _log_beta(1, b) + math.log(delta)

    def inside(p: float) -> bool:
        return errors * math.log(p) + (reviewed - errors) * math.log1p(-p) > floor

    # The observed rate is always inside: B(1+S, b+n-S)/B(1, b) is the prior's
    # average of L, at most L's maximum, L(S/n); with delta < 1 the floor is
    # below log L(S/n). So the interval runs from S/n up to the upper end:
    # inside below it, outside above it. Bisect until the interval stops
    # shrinking, as error_report.upper_error_bound does.
    low, high = errors / reviewed, 1.0
    while (middle := (low + high) / 2) not in (low, high):
        if inside(middle):
            low = middle
        else:
            high = middle
    return high


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def upper_bounds[S: BaseModel](policy: AcceptancePolicy, pack: Pack[S]) -> dict[str, float]:
    """Per field of the policy, the error rate its image-read evidence still allows.

    Each field is one of the pack's hypotheses, so each gets an equal share of
    ``1 - confidence`` (Bonferroni over every field of the pack, not only the
    ones with evidence: the count is fixed before any label).
    """
    if policy.pack != pack.name:
        raise ValueError(f"the policy is for the {policy.pack} pack, not {pack.name}")
    fields = list(pack.schema.model_fields)
    unknown = [name for name in policy.evidence if name not in fields]
    if unknown:
        raise ValueError(f"the policy names fields not in {pack.name}: {', '.join(unknown)}")
    delta = (1 - policy.confidence) / len(fields)
    return {
        name: anytime_upper_bound(
            evidence.errors, evidence.reviewed, target=policy.target, delta=delta
        )
        for name, evidence in policy.evidence.items()
    }


def accepted_fields[S: BaseModel](policy: AcceptancePolicy, pack: Pack[S]) -> frozenset[str]:
    """The fields whose image-read values ``policy`` accepts without review."""
    return frozenset(
        name for name, bound in upper_bounds(policy, pack).items() if bound < policy.target
    )


def calibrate[S: BaseModel](
    labels: Iterable[Label],
    pack: Pack[S],
    *,
    target: float,
    runs: list[str],
    audit_rate: float = DEFAULT_AUDIT_RATE,
) -> AcceptancePolicy:
    """The policy that ``labels`` support: image-read evidence for every field of ``pack``.

    Only queued labels count: before a field is accepted, all its image-read
    values are queued; after, only the audit draw is. A verdict on an accepted
    row was the reviewer's pick, and a picked sample voids the bound. A label
    is wrong when the reviewer's value differs from the run's, as in
    ``doc_intake.error_report``.
    """
    counts = {name: [0, 0] for name in pack.schema.model_fields}
    for label in labels:
        if label.source != "image" or not label.queued:
            continue
        count = counts[label.field]
        count[0] += 1
        count[1] += int(label.truth != label.suggested)
    return AcceptancePolicy(
        pack=pack.name,
        target=target,
        audit_rate=audit_rate,
        evidence={name: FieldEvidence(reviewed=n, errors=k) for name, (n, k) in counts.items()},
        runs=runs,
    )


def audit[S: BaseModel](
    result: ExtractionResult[S],
    accepted: frozenset[str],
    *,
    rate: float,
    draw: Callable[[], float],
) -> ExtractionResult[S]:
    """``result`` with a random share of its auto-accepted values sent back to review.

    A value was auto-accepted when its field is in ``accepted``, it was read
    from the image and it is not under review for another reason. Each one is
    drawn once (``draw`` returns a uniform number in [0, 1)) and goes to
    review when the draw is under ``rate``.
    """
    if result.fields is None:
        return result
    review = set(result.review)
    errors = list(result.errors)
    for name in type(result.fields).model_fields:
        field = getattr(result.fields, name)
        if name not in accepted or name in review or not is_field(field):
            continue
        citation = field.citation
        if citation is None or citation.source != "image":
            continue
        if draw() < rate:
            review.add(name)
            errors.append(
                f"{name}: audit sample of values accepted from the image;"
                f" check it on page {citation.page}"
            )
    if len(review) == len(result.review):
        return result
    # Built anew, not model_copy(update=...), which skips validation.
    return type(result)(
        status="needs_review",
        fields=result.fields,
        errors=errors,
        review=[name for name in type(result.fields).model_fields if name in review],
    )
