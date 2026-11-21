"""Extract a pack's fields from a document with an LLM, validated and cited.

The flow for one document (``docs/ARCHITECTURE.md`` D1-D3):

1. ask the provider for JSON that fills the pack's schema;
2. validate it with the schema (Pydantic); when it is invalid, ask again with
   the rejected answer and the validation errors, up to ``max_retries`` times;
   when retries run out, the result is ``failed`` with no fields (never partial);
3. check every citation against the page text it names; a quote that is not
   there downgrades the result to ``needs_review``.

Transport errors (network, authentication, rate limit after the SDK's own
retries) are not validation failures: they propagate to the caller, which
reports the document instead of skipping it.
"""

from dataclasses import dataclass
from typing import TypeIs

from pydantic import BaseModel, ValidationError

from core.ingest import Document, PageText
from core.llm import ImageInput, LLMProvider, LLMRequest
from core.result import Citation, ExtractedField, ExtractionResult

ENGINE_INSTRUCTIONS = """\
You extract fields from one document. Its text is given page by page, as read \
from the file. A page read by OCR also comes with its image, shown before the \
text; OCR text may contain recognition errors.

For every field, return exactly one of:
- a value, with a citation: the page number, the source and a quote showing \
where the value was read.
  - source "text": the quote is copied character for character from that \
page's text. Use it whenever the page's text shows the value correctly.
  - source "image": the quote is the text exactly as printed on the page image. \
Use it only when the page's text misreads or misses what the image shows.
  A field read as printed (listed below) has its value spelled exactly as in \
its quote, with nothing added that is not printed (no commas, words or \
corrections), and its quote covers the whole value, every line of it; the \
quote may hold more than the value. Other fields are converted as their \
description says, and their quote keeps the printed text.
- null as the value, with citation null and a short reason saying why the \
document does not show it.

Never guess or infer a value the document does not show, and never correct a \
reading from general knowledge: only the page text and the page image are \
evidence. A reason is only for a null value. Reply with JSON that matches the \
schema, and nothing else."""


@dataclass(frozen=True, slots=True)
class Pack[S: BaseModel]:
    """A document type: the schema to fill and the instructions specific to it."""

    name: str
    schema: type[S]
    instructions: str
    # Fields whose value is the text as printed: a value must sit inside its
    # quote (D11). The others are converted (a code, a date) and are not.
    printed: frozenset[str]

    def __post_init__(self) -> None:
        unknown = self.printed - set(self.schema.model_fields)
        if unknown:
            raise ValueError(f"printed fields not in the schema: {', '.join(sorted(unknown))}")


def extract[S: BaseModel](
    document: Document, pack: Pack[S], provider: LLMProvider, *, max_retries: int = 2
) -> ExtractionResult[S]:
    """Fill ``pack.schema`` from ``document``; see the module docstring for the flow."""
    if max_retries < 0:
        raise ValueError(f"max_retries must be 0 or more, got {max_retries}")
    instructions = _instructions(pack)
    images = _page_images(document)
    prompt = _document_prompt(document)
    errors: list[str] = []
    for _ in range(1 + max_retries):
        request = LLMRequest(
            instructions=instructions,
            images=images,
            prompt=prompt,
            schema_name=pack.name,
            output_schema=pack.schema,
        )
        answer = provider.complete(request).text
        try:
            fields = pack.schema.model_validate_json(answer)
        except ValidationError as error:
            errors = _describe(error)
            prompt = _retry_prompt(_document_prompt(document), answer, errors)
            continue
        problems = _citation_problems(fields, document, pack.printed)
        if problems:
            return ExtractionResult[S](
                status="needs_review",
                fields=fields,
                errors=[f"{name}: {problem}" for name, problem in problems.items()],
                review=list(problems),
            )
        return ExtractionResult[S](status="ok", fields=fields)
    return ExtractionResult[S](status="failed", errors=errors)


def _instructions[S: BaseModel](pack: Pack[S]) -> str:
    # Field descriptions also live in the schema, but a provider may drop them
    # there (Anthropic's transform_schema drops a description beside a $ref).
    guide = "\n".join(
        f"- {name}: {info.description}"
        for name, info in pack.schema.model_fields.items()
        if info.description
    )
    parts = [ENGINE_INSTRUCTIONS, pack.instructions]
    if pack.printed:
        parts.append(f"Fields read as printed: {', '.join(sorted(pack.printed))}.")
    if guide:
        parts.append(f"Fields:\n{guide}")
    return "\n\n".join(parts)


def _page_images(document: Document) -> tuple[ImageInput, ...]:
    # "Introduce each one with a short text label" (Anthropic docs, "Vision",
    # multiple images), so the model can tie an image to its page number.
    return tuple(
        ImageInput(
            label=f"Image of page {page.number}:",
            media_type=page.image.media_type,
            data=page.image.data,
        )
        for page in document.pages
        if page.image is not None
    )


def _document_prompt(document: Document) -> str:
    pages = "\n".join(
        f'<page number="{page.number}">\n{page.text}\n</page>' for page in document.pages
    )
    return f"<document>\n{pages}\n</document>"


def _retry_prompt(document_prompt: str, rejected: str, errors: list[str]) -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    return (
        f"{document_prompt}\n\n"
        "Your previous answer was rejected by the schema validation.\n"
        f"<rejected_answer>\n{rejected}\n</rejected_answer>\n"
        f"<validation_errors>\n{listed}\n</validation_errors>\n"
        "Return a corrected answer for the whole document."
    )


def _describe(error: ValidationError) -> list[str]:
    """Location and rule of each error, without the offending input.

    The input is document content, and these errors end up in the result and
    in logs (AGENTS.md invariant 6). The provider still sees the rejected
    answer, in the retry prompt.
    """
    described: list[str] = []
    for detail in error.errors(include_url=False, include_input=False, include_context=False):
        location = ".".join(str(part) for part in detail["loc"])
        described.append(f"{location}: {detail['msg']}" if location else detail["msg"])
    return described


def _citation_problems(
    fields: BaseModel, document: Document, printed: frozenset[str]
) -> dict[str, str]:
    """What a person must check, by field name in schema order; one problem per field.

    - a "text" quote must appear on the page it names;
    - an "image" quote cannot be checked by code, so it always goes to review
      (``docs/ARCHITECTURE.md`` D12), and it must cite a page whose image was sent;
    - a field read as printed must have its value inside its quote (D11).

    Comparison ignores how whitespace is laid out (a model often copies a
    multi-line passage as one line), and nothing else: case, punctuation and
    OCR errors must match, so a paraphrase is caught.
    """
    pages = {page.number: page for page in document.pages}
    problems: dict[str, str] = {}
    for name in type(fields).model_fields:
        field = getattr(fields, name)
        if not _is_field(field) or field.citation is None:
            continue
        text = field.value if name in printed and isinstance(field.value, str) else None
        problem = _citation_problem(text, field.citation, pages)
        if problem is not None:
            problems[name] = problem
    return problems


def _citation_problem(
    text: str | None, citation: Citation, pages: dict[int, PageText]
) -> str | None:
    """The first problem found, or None; ``text`` is the value of a printed field."""
    page = pages.get(citation.page)
    if page is None:
        return f"cites page {citation.page}, but the document has {len(pages)} pages"
    quote = _squash(citation.quote)
    if citation.source == "text" and quote not in _squash(page.text):
        return f"quote not found on page {citation.page}"
    if citation.source == "image" and page.image is None:
        return f"cites the image of page {citation.page}, which was not sent"
    if text is not None and _squash(text) not in quote:
        return "value is not the text of its quote"
    if citation.source == "image":
        return f"read from the image of page {citation.page}; check it on the page"
    return None


def _squash(text: str) -> str:
    return " ".join(text.split())


def _is_field(value: object) -> TypeIs[ExtractedField[object]]:
    # getattr loses the field's type parameter; isinstance alone would leave it
    # Unknown, which strict pyright rejects (PEP 742).
    return isinstance(value, ExtractedField)
