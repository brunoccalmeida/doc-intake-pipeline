"""Print an extraction result one line per field, for the demo video to fit a screen.

    uv run poe extract --replay demo/recordings demo/receipt.png | uv run python -m demo.show_result

Reads the JSON that ``extract`` prints and shows, per field, the value and the
evidence it was read from, or null and the reason. Presentation only: the
JSON on stdin is the result, and the video shows the command that made it.
"""

import sys

from pydantic import BaseModel

from core.result import ExtractedField


class _Shown(BaseModel):
    status: str
    # Every value arrives as JSON text (a Decimal and a date are strings), so
    # one type reads any pack's fields without knowing the pack.
    fields: dict[str, ExtractedField[str]] | None
    errors: list[str]


def _line(name: str, field: ExtractedField[str]) -> str:
    if field.value is None or field.citation is None:
        return f"{name:<9} null  <- {field.reason}"
    quote = field.citation.quote.replace("\n", " / ")
    return (
        f"{name:<9} {field.value.replace(chr(10), ' / ')}  "
        f'<- page {field.citation.page} {field.citation.source}: "{quote}"'
    )


def main() -> None:
    result = _Shown.model_validate_json(sys.stdin.read())
    print(f"status: {result.status}")
    for name, field in (result.fields or {}).items():
        print(_line(name, field))
    for error in result.errors:
        print(f"review: {error}")


if __name__ == "__main__":
    main()
