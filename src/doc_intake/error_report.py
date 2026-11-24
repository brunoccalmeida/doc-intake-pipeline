"""The per-field error report of reviewed runs (#64, docs/ARCHITECTURE.md D21).

Each reviewed field (``doc_intake.review.Label``) is counted under its pack
field and the source the run read it from: ``text``, ``image`` or ``empty``
(the run left it empty). A field is wrong when the reviewer's value differs
from the run's, whatever the verdict says: ``not_on_page`` on a field the run
left empty is right.

Per row, the report gives the error rate seen and its one-sided 95% upper
bound, the exact (Clopper-Pearson) one: the error rate that the reviewed
sample still cannot rule out. With no error in ``n`` fields it is about
``3/n`` (the rule of three), so a clean sample of 100 fields still allows 3%.

The report holds field names, counts and rates only, never a value
(AGENTS.md invariant 6).
"""

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from doc_intake.core.extract import Pack
from doc_intake.review import Label

type Source = Literal["text", "image", "empty"]
_SOURCES: tuple[Source, ...] = ("text", "image", "empty")
CONFIDENCE = 0.95


@dataclass(frozen=True, slots=True)
class FieldErrors:
    """The reviewed fields of one pack field read from one source."""

    field: str
    source: Source
    reviewed: int
    errors: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.reviewed

    @property
    def upper_bound(self) -> float:
        """The one-sided 95% upper bound of the error rate (Clopper-Pearson)."""
        return upper_error_bound(self.errors, self.reviewed)


def error_report[S: BaseModel](labels: Iterable[Label], pack: Pack[S]) -> list[FieldErrors]:
    """One row per field and source that has a reviewed field, in schema order."""
    fields = list(pack.schema.model_fields)
    reviewed: Counter[tuple[str, Source]] = Counter()
    errors: Counter[tuple[str, Source]] = Counter()
    for label in labels:
        if label.field not in fields:
            raise ValueError(f"{label.file}: {label.field} is not a field of {pack.name}")
        key = (label.field, label.source or "empty")
        reviewed[key] += 1
        errors[key] += int(label.truth != label.suggested)
    return [
        FieldErrors(field, source, reviewed[key], errors[key])
        for field in fields
        for source in _SOURCES
        if (key := (field, source)) in reviewed
    ]


def upper_error_bound(errors: int, reviewed: int, confidence: float = CONFIDENCE) -> float:
    """The exact one-sided upper confidence bound of a binomial error rate.

    Clopper and Pearson (1934): the error rate ``p`` at which seeing at most
    ``errors`` wrong fields in ``reviewed`` has probability ``1 - confidence``.
    Any higher rate would make so few errors less likely than that. With every
    field wrong, that probability is 1 at any rate, no rate is ruled out, and
    the bisection below ends at 1.
    """
    if not 0 <= errors <= reviewed or reviewed < 1:
        raise ValueError(f"{errors} errors in {reviewed} reviewed fields is not a sample")
    alpha = 1 - confidence
    # P(X <= errors) falls as p grows: bisect until the interval stops shrinking.
    low, high = 0.0, 1.0
    while (middle := (low + high) / 2) not in (low, high):
        if _at_most(errors, reviewed, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def _at_most(errors: int, reviewed: int, p: float) -> float:
    """P(X <= errors) for X ~ Binomial(reviewed, p), with 0 < p < 1.

    Summed in logs, because ``p ** i`` underflows for large samples.
    """
    log_p, log_q = math.log(p), math.log1p(-p)
    return math.fsum(
        math.exp(math.log(math.comb(reviewed, i)) + i * log_p + (reviewed - i) * log_q)
        for i in range(errors + 1)
    )
