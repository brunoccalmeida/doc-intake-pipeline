"""Write a client's acceptance policy from reviewed run folders (#65).

    uv run poe calibrate --target 0.02 --out POLICY RUNS/2026-11-22T15-30-00Z [RUNS/... ...]
    uv run poe calibrate --pack invoice ...  # default pack: receipt

Counts, per field of the pack, the values read from the page image that reviewers
checked and how many were wrong (``doc_intake.review``), writes them with the
target to POLICY (``doc_intake.acceptance``) and prints, per field, the upper
bound of its error rate and whether the policy accepts it. Point
``DOC_INTAKE_ACCEPTANCE_POLICY`` at POLICY to apply it to the next runs.

Calibrate as often as labels arrive: the bound stays valid however often it
is looked at (docs/ARCHITECTURE.md D22). Fix the target before looking, not
after: a target chosen to let a field pass is no target.

A policy is for one pack: POLICY holding another pack's policy is never
replaced, since that would drop its labels; each pack has its own file.

Field names and numbers only, never a value (AGENTS.md invariant 6). Exits 1,
writing no policy, when a folder cannot be read or no image-read value was
reviewed.
"""

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel

from doc_intake.acceptance import (
    DEFAULT_AUDIT_RATE,
    AcceptancePolicy,
    calibrate,
    load_policy,
    upper_bounds,
)
from doc_intake.core.extract import Pack
from doc_intake.packs.invoice import INVOICE
from doc_intake.packs.receipt import RECEIPT
from doc_intake.review import Label, ReviewError, read_reviewed_run
from scripts.packs import add_pack_argument

COLUMNS = ("field", "reviewed", "errors", "upper bound", "accepted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("folders", type=Path, nargs="+", help="reviewed run folders")
    parser.add_argument(
        "--target", type=float, required=True, help="highest error rate to accept, e.g. 0.02"
    )
    parser.add_argument(
        "--audit-rate",
        type=float,
        default=DEFAULT_AUDIT_RATE,
        help=f"share of accepted values sent back to review (default {DEFAULT_AUDIT_RATE})",
    )
    parser.add_argument("--out", type=Path, required=True, help="the policy file to write")
    add_pack_argument(parser)
    args = parser.parse_args(argv)
    folders: list[Path] = args.folders
    out: Path = args.out
    target: float = args.target
    audit_rate: float = args.audit_rate

    # One call per pack, not a lookup: each pack keeps its own schema type.
    match args.pack:
        case INVOICE.name:
            return _calibrate(INVOICE, folders, out, target=target, audit_rate=audit_rate)
        case _:
            return _calibrate(RECEIPT, folders, out, target=target, audit_rate=audit_rate)


def _calibrate[S: BaseModel](
    pack: Pack[S], folders: list[Path], out: Path, *, target: float, audit_rate: float
) -> int:
    labels: list[Label] = []
    runs: list[str] = []
    # A folder given twice would count its reviews twice and narrow the
    # bound, the unsafe side: each counts once.
    for folder in dict.fromkeys(folder.resolve() for folder in folders):
        try:
            labels += read_reviewed_run(folder, pack)
        except ReviewError as error:
            print(f"{folder.name}: {error}", file=sys.stderr)
            return 1
        runs.append(folder.name)
    if not any(label.source == "image" and label.queued for label in labels):
        print(
            "no value read from the image was reviewed: fill in the verdict column first",
            file=sys.stderr,
        )
        return 1
    if out.exists():
        problem = _breaks_the_sequence(load_policy(out), pack, target=target, runs=runs)
        if problem:
            print(f"{out}: {problem}", file=sys.stderr)
            return 1
    policy = calibrate(labels, pack, target=target, audit_rate=audit_rate, runs=runs)
    # Through a temporary file: a scheduled run may load the policy meanwhile.
    temporary = out.with_name(f".{out.name}.tmp")
    temporary.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(out)  # atomic on one filesystem (os.replace)
    print(render(policy, pack))
    return 0


def _breaks_the_sequence[S: BaseModel](
    previous: AcceptancePolicy, pack: Pack[S], *, target: float, runs: list[str]
) -> str:
    """Why a new policy cannot replace ``previous``, or "" when it can.

    The bound holds however often it is looked at only along one growing
    sequence of labels, checked against one target fixed in advance
    (docs/ARCHITECTURE.md D22). Leaving out a run with an error, or moving the
    target, would pick the result. A policy for another pack is another decision.
    """
    if previous.pack != pack.name:
        return (
            f"it holds the policy for the {previous.pack} pack, not {pack.name}; "
            "write each pack's policy to its own file"
        )
    if target != previous.target:
        return (
            f"its target is {previous.target}; a target changed after seeing the reviews "
            "voids the bound (write a new policy file only for a new decision)"
        )
    missing = [run for run in previous.runs if run not in runs]
    if missing:
        return (
            f"it was calibrated on {', '.join(missing)}, not given now; "
            "calibrate on every reviewed run since the first"
        )
    return ""


def render[S: BaseModel](policy: AcceptancePolicy, pack: Pack[S]) -> str:
    """The policy as a table: names left-aligned, numbers right-aligned."""
    bounds = upper_bounds(policy, pack)
    cells = [COLUMNS] + [
        (
            name,
            str(evidence.reviewed),
            str(evidence.errors),
            f"{bounds[name]:.3%}",
            "yes" if bounds[name] < policy.target else "no",
        )
        for name, evidence in policy.evidence.items()
    ]
    widths = [max(len(line[i]) for line in cells) for i in range(len(COLUMNS))]
    left = (0, len(COLUMNS) - 1)
    lines = [
        "  ".join(
            cell.ljust(width) if i in left else cell.rjust(width)
            for i, (cell, width) in enumerate(zip(line, widths, strict=True))
        ).rstrip()
        for line in cells
    ]
    fields = len(pack.schema.model_fields)
    confidence = f"{policy.confidence:.0%}"
    note = (
        f"target {policy.target:.3%}, audit {policy.audit_rate:.0%} of accepted values.\n"
        "upper bound: the highest error rate of the values read from the image that\n"
        f"the reviewed ones cannot rule out, with {confidence} confidence shared by the\n"
        f"{fields} fields (a confidence sequence: valid however often you calibrate).\n"
        "A field is accepted when its bound is under the target."
    )
    return "\n".join([*lines, "", note])


if __name__ == "__main__":
    sys.exit(main())
