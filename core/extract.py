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

from pydantic import BaseModel, ValidationError

from core.ingest import Document
from core.llm import LLMProvider, LLMRequest
from core.result import ExtractedField, ExtractionResult

ENGINE_INSTRUCTIONS = """\
You extract fields from one document. Its text is given page by page, as read \
from the file (OCR text may contain recognition errors).

For every field, return exactly one of:
- a value, with a citation: the page number and a quote copied character for \
character from that page's text, showing where the value was read;
- null as the value, with citation null and a short reason saying why the \
document does not show it.

Never guess or infer a value the document does not show. A reason is only for \
a null value. Reply with JSON that matches the schema, and nothing else."""


@dataclass(frozen=True, slots=True)
class Pack[S: BaseModel]:
    """A document type: the schema to fill and the instructions specific to it."""

    name: str
    schema: type[S]
    instructions: str


def extract[S: BaseModel](
    document: Document, pack: Pack[S], provider: LLMProvider, *, max_retries: int = 2
) -> ExtractionResult[S]:
    """Fill ``pack.schema`` from ``document``; see the module docstring for the flow."""
    if max_retries < 0:
        raise ValueError(f"max_retries must be 0 or more, got {max_retries}")
    instructions = _instructions(pack)
    prompt = _document_prompt(document)
    errors: list[str] = []
    for _ in range(1 + max_retries):
        request = LLMRequest(
            instructions=instructions,
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
        problems = _citation_problems(fields, document)
        if problems:
            return ExtractionResult[S](status="needs_review", fields=fields, errors=problems)
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
    if guide:
        parts.append(f"Fields:\n{guide}")
    return "\n\n".join(parts)


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


def _citation_problems(fields: BaseModel, document: Document) -> list[str]:
    """Every cited quote must appear on the page it names.

    Comparison ignores how whitespace is laid out (a model often copies a
    multi-line passage as one line), and nothing else: case, punctuation and
    OCR errors must match, so a paraphrase is caught.
    """
    pages = {page.number: _squash(page.text) for page in document.pages}
    problems: list[str] = []
    for name in type(fields).model_fields:
        field = getattr(fields, name)
        if not isinstance(field, ExtractedField) or field.citation is None:
            continue
        citation = field.citation
        page_text = pages.get(citation.page)
        if page_text is None:
            problems.append(
                f"{name}: cites page {citation.page}, but the document has {len(pages)} pages"
            )
        elif _squash(citation.quote) not in page_text:
            problems.append(f"{name}: quote not found on page {citation.page}")
    return problems


def _squash(text: str) -> str:
    return " ".join(text.split())
