"""A reviewed run folder read back as labeled fields (#63, docs/ARCHITECTURE.md D20).

``doc_intake.batch`` writes each run's review queue, ``results.csv``, with two
columns for the reviewer: ``verdict`` and ``correct_value``. A verdict is one of

- ``confirmed``: what the run produced is right (an empty field: it is absent);
- ``corrected``: the right value is in ``correct_value``, as the pack's schema
  takes it (a decimal with a dot, a date as YYYY-MM-DD);
- ``not_on_page``: the field is not on the document.

An empty verdict means not reviewed, never confirmed. A labeled field pairs
what the run suggested with what the reviewer says is true; the run's
suggestions come from its machine copy, ``results.jsonl``, because a
spreadsheet may rewrite the value column it shows (a date in the local format).

Anything that cannot become a label fails, naming the sheet row: a label read
wrong would silently bias every measure built on it. Messages name rows and
fields, never a value (AGENTS.md invariant 6).
"""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeIs, get_args

from pydantic import BaseModel, TypeAdapter, ValidationError

from doc_intake.batch import COPY_NAME, RESULTS_NAME, VERDICT_COLUMNS, spreadsheet_safe
from doc_intake.core.extract import Pack
from doc_intake.core.result import ExtractionResult, is_field

type Verdict = Literal["confirmed", "corrected", "not_on_page"]
_VERDICTS: tuple[str, ...] = get_args(Verdict.__value__)
_KEY_COLUMNS = ("file", "field")
# Excel saves CSV with the list separator of the region's settings: ";" where
# the decimal separator is a comma (pt-BR, de-DE).
_DELIMITERS = (",", ";")


class ReviewError(ValueError):
    """A reviewed run folder that cannot be read as labels; the message says where."""


@dataclass(frozen=True, slots=True)
class Label:
    """One reviewed field: the run's suggestion and the value on the page.

    ``suggested`` and ``truth`` have the pack's types (``Decimal``, ``date``,
    ``str``); ``None`` means empty, and absent from the page for ``truth``.
    """

    file: str
    field: str
    verdict: Verdict
    suggested: object
    truth: object


def read_reviewed_run[S: BaseModel](folder: Path, pack: Pack[S]) -> list[Label]:
    """The reviewed fields of ``folder``, in the run's order (file, then schema order)."""
    suggested = _suggestions(folder / COPY_NAME, pack)
    labels: dict[tuple[str, str], Label] = {}
    seen: dict[tuple[str, str], int] = {}
    files = {file for file, _ in suggested}
    for number, row in _sheet_rows(folder / RESULTS_NAME):
        file, field = _unguarded(row.get("file") or ""), row.get("field") or ""
        where = f"row {number} ({file}, {field})" if field else f"row {number} ({file})"
        key = (file, field)
        if key in seen:
            raise ReviewError(f"{where}: also in row {seen[key]}; keep one row per field")
        seen[key] = number
        verdict = (row.get("verdict") or "").strip().lower()
        correct = (row.get("correct_value") or "").strip()
        if not field and file in files:
            if verdict or correct:
                raise ReviewError(f"{where}: a failed document has no fields to review")
            continue
        if key not in suggested:
            raise ReviewError(f"{where}: not in this run's {COPY_NAME}")
        label = _label(where, pack, file, field, verdict, correct, suggested[key])
        if label is not None:
            labels[key] = label
    return [labels[key] for key in suggested if key in labels]


def _label[S: BaseModel](
    where: str,
    pack: Pack[S],
    file: str,
    field: str,
    verdict: str,
    correct: str,
    suggestion: object,
) -> Label | None:
    if not verdict:
        if correct:
            raise ReviewError(f"{where}: a correct_value but no verdict; add one")
        return None
    if not _is_verdict(verdict):
        # Not echoed: a value pasted one column off would reach the message.
        raise ReviewError(f"{where}: unknown verdict; use one of {', '.join(_VERDICTS)}")
    if verdict != "corrected":
        if correct:
            raise ReviewError(f"{where}: only a corrected verdict takes a correct_value")
        truth = suggestion if verdict == "confirmed" else None
        return Label(file, field, verdict, suggested=suggestion, truth=truth)
    if not correct:
        raise ReviewError(f"{where}: corrected needs the right value in correct_value")
    try:
        truth = _value_type(pack, field).validate_python(correct)
    except ValidationError as error:
        # Without the input: Pydantic's messages would otherwise quote it.
        problems = "; ".join(e["msg"] for e in error.errors(include_input=False))
        raise ReviewError(f"{where}: correct_value is not a valid {field}: {problems}") from None
    return Label(file, field, verdict, suggested=suggestion, truth=truth)


def _is_verdict(text: str) -> TypeIs[Verdict]:
    return text in _VERDICTS


def _unguarded(cell: str) -> str:
    """The file name in ``cell`` without the ``'`` that ``spreadsheet_safe`` added.

    The run writes ``-scan.png`` as ``'-scan.png``; a spreadsheet may keep
    that quote in the cell or drop it when saving, so both name the file.
    """
    if cell.startswith("'") and spreadsheet_safe(cell[1:]) == cell:
        return cell[1:]
    return cell


def _value_type[S: BaseModel](pack: Pack[S], field: str) -> TypeAdapter[object]:
    """The type of the field's value in the pack's schema, as a validator."""
    wrapper = pack.schema.model_fields[field].annotation
    value = (
        wrapper.model_fields["value"].annotation
        if isinstance(wrapper, type) and issubclass(wrapper, BaseModel)
        else None
    )
    if value is None:
        # Every pack field is an ExtractedField[T] (core.result); anything else
        # is a pack written wrong, not a reviewer's mistake.
        raise TypeError(f"{pack.name}.{field} is not an ExtractedField")
    return TypeAdapter[object](value)


def _suggestions[S: BaseModel](path: Path, pack: Pack[S]) -> dict[tuple[str, str], object]:
    """What the run produced per (file, field); a failed document keys (file, "")."""
    suggested: dict[tuple[str, str], object] = {}
    result_type = ExtractionResult[pack.schema]
    if not path.is_file():
        raise ReviewError(
            f"{path.parent.name} has no {path.name}: a run from before #63 cannot be read as labels"
        )
    for line in path.read_text(encoding="utf-8").splitlines():
        copy = json.loads(line)
        file = str(copy["file"])
        fields = result_type.model_validate(copy["result"]).fields
        if fields is None:
            suggested[(file, "")] = None
            continue
        for name in type(fields).model_fields:
            value = getattr(fields, name)
            if is_field(value):
                suggested[(file, name)] = value.value
    return suggested


def _sheet_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    """The sheet's rows with their row numbers (the header is row 1)."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ReviewError(
            f'{path.name} is not UTF-8: save it as "CSV UTF-8 (Comma delimited)"'
        ) from None
    header = text.splitlines()[0] if text else ""
    for delimiter in _DELIMITERS:
        columns = next(csv.reader([header], delimiter=delimiter))
        if all(column in columns for column in _KEY_COLUMNS):
            break
    else:
        raise ReviewError(f"{path.name} has no file and field columns")
    missing = [column for column in VERDICT_COLUMNS if column not in columns]
    if missing:
        raise ReviewError(f"{path.name} has no {', '.join(missing)} column")
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    return list(enumerate(reader, start=2))
