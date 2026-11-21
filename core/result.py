"""Generic extraction result: a value with its evidence, or an explained absence.

Packs describe their documents with ``ExtractedField`` attributes; the engine
wraps a pack's schema in ``ExtractionResult``. The rules below live in the
types, not in caller code, so every producer (LLM output, golden set, tests)
is held to them by construction:

- a value requires a citation of where it was read (``docs/ARCHITECTURE.md`` D1);
- an empty value requires the reason it is empty, never a plausible guess;
- a result that is not ``ok`` says why, and a failure carries no partial fields.
"""

import re
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    model_validator,
)

# At least one visible character, but kept as given: a quote stays literal.
type NonBlankText = Annotated[str, StringConstraints(pattern=r"\S")]

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_date_text_only(value: object) -> object:
    """Let only ``YYYY-MM-DD`` text (or a ``date``) reach Pydantic's date parser.

    Pydantic's lax mode, and its strict mode for text, also read a Unix
    timestamp as a date, so any number on a document could become a date.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        return value
    raise ValueError("expected an ISO 8601 calendar date as text: YYYY-MM-DD")


type IsoDate = Annotated[date, BeforeValidator(_iso_date_text_only)]


class StrictModel(BaseModel, frozen=True, extra="forbid"):
    """Base of every schema: immutable, and an unknown key is an error.

    An extra key means the producer is not following the schema, so it fails
    instead of being dropped silently.

    The config is given as class arguments, not ``model_config``, because type
    checkers read only those (Pydantic docs, "Configuration"). Type checkers do
    not inherit ``frozen`` (PEP 681), so every subclass repeats
    ``frozen=True``; pyright rejects a subclass that forgets it.
    """


type QuoteSource = Literal["text", "image"]


# The docstring is the schema description the LLM reads, so it speaks to the
# model. Why "image" quotes send the result to review: docs/ARCHITECTURE.md D12.
class Citation(StrictModel, frozen=True):
    """Where a value was read: the page (numbered from 1), the source and the literal text.

    source "text": the quote is copied from the page's text. source "image": the
    quote is the text as printed on the page image, used only where the page's
    text misreads or misses it.
    """

    page: Annotated[int, Field(ge=1)]
    source: QuoteSource
    quote: NonBlankText


class ExtractedField[T](StrictModel, frozen=True):
    """One field: either a value with its citation, or ``None`` with a reason.

    Every key is required, even when null: a producer states the evidence or
    its absence explicitly. It also matches what providers' strict structured
    output demands (OpenAI requires every property in ``required``).
    """

    value: T | None
    citation: Citation | None
    reason: NonBlankText | None

    @model_validator(mode="after")
    def _evidence_matches_value(self) -> Self:
        if isinstance(self.value, str) and not self.value.strip():
            # "" is how an LLM often says "not found": an absence, not a value.
            raise ValueError("blank text is not a value; use null with a reason")
        if self.value is not None:
            if self.citation is None:
                raise ValueError("a value requires a citation")
            if self.reason is not None:
                raise ValueError("a reason only explains an empty value")
        else:
            if self.reason is None:
                raise ValueError("an empty value requires a reason")
            if self.citation is not None:
                raise ValueError("a citation needs a value to cite")
        return self


type Status = Literal["ok", "needs_review", "failed"]


class ExtractionResult[S: BaseModel](StrictModel, frozen=True):
    """The outcome for one document, wrapping the pack's schema ``S``.

    ``ok``: fields, no errors. ``needs_review``: fields plus what a human must
    check, with ``review`` naming those fields (each once, in schema order) so
    a caller routes them without parsing ``errors``; every other field was
    accepted. ``failed``: no fields (never partial), only the errors.
    """

    status: Status
    fields: S | None = None
    errors: list[NonBlankText] = Field(default_factory=list[str])
    review: list[str] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _status_matches_content(self) -> Self:
        if self.status != "ok" and not self.errors:
            raise ValueError(f"a result with status {self.status!r} must say why in errors")
        if self.status != "needs_review" and self.review:
            raise ValueError("only a needs_review result names fields to review")
        if self.status == "needs_review" and not self.review:
            raise ValueError("a needs_review result must name the fields to check in review")
        if len(set(self.review)) != len(self.review):
            raise ValueError("review names a field twice")
        if self.fields is not None:
            unknown = [name for name in self.review if name not in type(self.fields).model_fields]
            if unknown:
                raise ValueError(f"review names fields not in the schema: {', '.join(unknown)}")
        match self.status:
            case "ok" if self.errors:
                raise ValueError("an ok result carries no errors")
            case "failed" if self.fields is not None:
                raise ValueError("a failed result carries no fields")
            case "ok" | "needs_review" if self.fields is None:
                raise ValueError(f"a result with status {self.status!r} requires fields")
            case _:
                return self
