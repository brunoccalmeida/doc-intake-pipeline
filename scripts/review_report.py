"""Print the per-field error report of reviewed run folders (#64).

    uv run poe review-report RUNS/2026-11-22T153000Z [RUNS/... ...]
    uv run poe review-report --pack invoice ...  # default pack: receipt

Reads each folder's review (``doc_intake.review``) and prints one row per
field of the pack and source: fields reviewed, fields wrong, the error rate and its
one-sided 95% upper bound (``doc_intake.error_report``). Field names and
numbers only, never a value (AGENTS.md invariant 6).

Exits 1, printing nothing on stdout, when a folder cannot be read (the message
names the folder and the row to fix) or when no field was reviewed.
"""

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel

from doc_intake.core.extract import Pack
from doc_intake.error_report import CONFIDENCE, FieldErrors, error_report
from doc_intake.packs.invoice import INVOICE
from doc_intake.packs.receipt import RECEIPT
from doc_intake.review import Label, ReviewError, read_reviewed_run
from scripts.packs import add_pack_argument

COLUMNS = ("field", "source", "reviewed", "errors", "error rate", f"upper {CONFIDENCE:.0%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("folders", type=Path, nargs="+", help="reviewed run folders")
    add_pack_argument(parser)
    args = parser.parse_args(argv)
    folders: list[Path] = args.folders

    # One call per pack, not a lookup: each pack keeps its own schema type.
    match args.pack:
        case INVOICE.name:
            return _report(INVOICE, folders)
        case _:
            return _report(RECEIPT, folders)


def _report[S: BaseModel](pack: Pack[S], folders: list[Path]) -> int:
    labels: list[Label] = []
    # A folder given twice (a repeated path, overlapping globs) would count its
    # reviews twice and narrow the bound, the unsafe side: each counts once.
    for folder in dict.fromkeys(folder.resolve() for folder in folders):
        try:
            labels += read_reviewed_run(folder, pack)
        except ReviewError as error:
            print(f"{folder.name}: {error}", file=sys.stderr)
            return 1
    rows = error_report(labels, pack)
    if not rows:
        print("no reviewed field: fill in the verdict column first", file=sys.stderr)
        return 1
    print(render(rows))
    return 0


def render(rows: list[FieldErrors]) -> str:
    """The report as a table: names left-aligned, numbers right-aligned."""
    cells = [COLUMNS] + [
        (
            row.field,
            row.source,
            str(row.reviewed),
            str(row.errors),
            f"{row.error_rate:.2%}",
            f"{row.upper_bound:.2%}",
        )
        for row in rows
    ]
    widths = [max(len(line[i]) for line in cells) for i in range(len(COLUMNS))]
    lines = [
        "  ".join(
            cell.ljust(width) if i < 2 else cell.rjust(width)
            for i, (cell, width) in enumerate(zip(line, widths, strict=True))
        ).rstrip()
        for line in cells
    ]
    level = f"{CONFIDENCE:.0%}"
    note = (
        f"upper {level}: the highest error rate these reviewed fields cannot rule out,\n"
        f"with {level} confidence (exact Clopper-Pearson bound). Only fields a person\n"
        "reviewed count: if the review covers flagged fields only, the bound says\n"
        "nothing about the fields the run accepted."
    )
    return "\n".join([*lines, "", note])


if __name__ == "__main__":
    sys.exit(main())
