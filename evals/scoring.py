"""Score one extraction against its golden record, field by field.

The rules, also in ``docs/ARCHITECTURE.md`` D4:

- **Text** matches after folding case and normalizing whitespace. SROIE's own
  protocol is an exact match of the extracted text (Huang et al., 2019,
  section III); its ground truth is all uppercase while receipts are not
  always, so case is folded, and how a line break was read is not content.
  Whitespace next to punctuation is dropped too: the annotators space it
  inconsistently (``"BAHRU,JOHOR"``, ``"19-G& 19-1"``), so a space after a
  comma is not an error. Anything else is wrong: a missing or extra
  punctuation mark, a misread character, two words run together.
- **Dates and money** match by value: the schema already normalizes them
  (ISO date, ``Decimal``), so ``9.0`` and ``9.00`` are the same total.
- **Empty versus value** is an error both ways: ``missing`` when the document
  shows the value and the result left it empty, ``unexpected`` when the result
  gives a value the golden record says is not there (invariant 1: nothing
  invented). Two empty fields match whatever the reasons say.
- A document that **failed** (unreadable file, or no valid answer after the
  retries) scores ``document_failed`` on every field, including an expected
  empty one: an answer that does not exist got nothing right.

Each field is also **routed** the way a client would receive it (D16):
``review`` when the result names it for a person to check, or when the
document failed (a failure goes to a person whole, invariant 2); ``empty``
when it has no value; ``accepted`` otherwise. A wrong value (``wrong`` or
``unexpected``) that is accepted reaches a client unchecked: that count is
gated. One caught by review is the system working.

Scores hold ids, field names and outcomes only, never document content, so
they can be published (AGENTS.md invariant 6).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Self, get_args

from pydantic import BaseModel, model_validator

from doc_intake.core.result import ExtractedField, ExtractionResult, Status, StrictModel

type FieldOutcome = Literal["correct", "wrong", "missing", "unexpected", "document_failed"]
type FieldRoute = Literal["accepted", "review", "empty"]

# Values that should not reach a client; "missing" is an empty field, not a value.
_WRONG_VALUES: frozenset[FieldOutcome] = frozenset({"wrong", "unexpected"})


class DocumentScore(StrictModel, frozen=True):
    """One document's status, and the outcome and route of each field, in schema order.

    ``error`` names the exception class when the file could not be read.
    """

    id: str
    status: Status
    fields: dict[str, FieldOutcome]
    routes: dict[str, FieldRoute]
    error: str | None = None

    @model_validator(mode="after")
    def _routes_match_outcomes(self) -> Self:
        if list(self.routes) != list(self.fields):
            raise ValueError("routes and outcomes name different fields")
        return self


@dataclass(frozen=True, slots=True)
class ReviewLoad:
    """How one field's values reached the client, and how many of them were wrong."""

    accepted: int
    review: int
    empty: int
    wrong_accepted: int = 0
    wrong_review: int = 0

    @classmethod
    def total(cls, loads: Iterable[ReviewLoad]) -> ReviewLoad:
        loads = list(loads)
        return cls(
            accepted=sum(load.accepted for load in loads),
            review=sum(load.review for load in loads),
            empty=sum(load.empty for load in loads),
            wrong_accepted=sum(load.wrong_accepted for load in loads),
            wrong_review=sum(load.wrong_review for load in loads),
        )


def field_outcome[T](expected: ExtractedField[T], predicted: ExtractedField[T]) -> FieldOutcome:
    """Compare one extracted field with the golden one; see the module docstring."""
    if expected.value is None:
        return "correct" if predicted.value is None else "unexpected"
    if predicted.value is None:
        return "missing"
    return "correct" if _same(expected.value, predicted.value) else "wrong"


def score_document[S: BaseModel](
    document_id: str, golden: S, result: ExtractionResult[S] | str
) -> DocumentScore:
    """Score ``result`` against ``golden``; a ``str`` result is the read error's class name."""
    names = list(type(golden).model_fields)
    failed: dict[str, FieldOutcome] = dict.fromkeys(names, "document_failed")
    to_person: dict[str, FieldRoute] = dict.fromkeys(names, "review")
    if isinstance(result, str):
        return DocumentScore(
            id=document_id, status="failed", fields=failed, routes=to_person, error=result
        )
    if result.fields is None:
        return DocumentScore(id=document_id, status=result.status, fields=failed, routes=to_person)
    fields: dict[str, FieldOutcome] = {}
    routes: dict[str, FieldRoute] = {}
    for name in names:
        predicted: ExtractedField[object] = getattr(result.fields, name)
        fields[name] = field_outcome(getattr(golden, name), predicted)
        if name in result.review:
            routes[name] = "review"
        else:
            routes[name] = "empty" if predicted.value is None else "accepted"
    return DocumentScore(id=document_id, status=result.status, fields=fields, routes=routes)


def field_accuracy(scores: Iterable[DocumentScore]) -> dict[str, tuple[int, int]]:
    """``(correct, documents)`` per field, in the order fields first appear."""
    accuracy: dict[str, tuple[int, int]] = {}
    for score in scores:
        for name, outcome in score.fields.items():
            correct, total = accuracy.get(name, (0, 0))
            accuracy[name] = (correct + (outcome == "correct"), total + 1)
    return accuracy


def review_load(scores: Iterable[DocumentScore]) -> dict[str, ReviewLoad]:
    """Per field, in the order fields first appear: where the values went, and the wrong ones."""
    counts: dict[str, dict[str, int]] = {}
    for score in scores:
        for name, route in score.routes.items():
            count = counts.setdefault(name, dict.fromkeys(_LOAD_KEYS, 0))
            count[route] += 1
            if route != "empty" and score.fields[name] in _WRONG_VALUES:
                count[f"wrong_{route}"] += 1
    return {name: ReviewLoad(**count) for name, count in counts.items()}


_LOAD_KEYS = ("accepted", "review", "empty", "wrong_accepted", "wrong_review")


def status_counts(scores: Iterable[DocumentScore]) -> dict[Status, int]:
    """How many documents ended in each status, zeros included."""
    counts: dict[Status, int] = dict.fromkeys(get_args(Status.__value__), 0)
    for score in scores:
        counts[score.status] += 1
    return counts


def _same(expected: object, predicted: object) -> bool:
    if isinstance(expected, str) and isinstance(predicted, str):
        return _fold(expected) == _fold(predicted)
    return expected == predicted


_SPACE_BY_PUNCTUATION = re.compile(r"\s*([^\w\s])\s*")


def _fold(text: str) -> str:
    collapsed = " ".join(text.split())
    return _SPACE_BY_PUNCTUATION.sub(r"\1", collapsed).casefold()
