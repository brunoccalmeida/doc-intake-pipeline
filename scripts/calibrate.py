"""Write a client's acceptance policy from reviewed run folders (#65).

    uv run poe calibrate --target 0.02 --out POLICY RUNS/2026-11-22T15-30-00Z [RUNS/... ...]

Counts, per receipt field, the values read from the page image that reviewers
checked and how many were wrong (``doc_intake.review``), writes them with the
target to POLICY (``doc_intake.acceptance``) and prints, per field, the upper
bound of its error rate and whether the policy accepts it. Point
``DOC_INTAKE_ACCEPTANCE_POLICY`` at POLICY to apply it to the next runs.

Calibrate as often as labels arrive: the bound stays valid however often it
is looked at (docs/ARCHITECTURE.md D22). Fix the target before looking, not
after: a target chosen to let a field pass is no target.

Field names and numbers only, never a value (AGENTS.md invariant 6). Exits 1,
writing no policy, when a folder cannot be read or no image-read value was
reviewed.
"""

import argparse
import sys
from pathlib import Path

from doc_intake.acceptance import (
    DEFAULT_AUDIT_RATE,
    AcceptancePolicy,
    calibrate,
    load_policy,
    upper_bounds,
)
from doc_intake.packs.receipt import RECEIPT
from doc_intake.review import Label, ReviewError, read_reviewed_run

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
    args = parser.parse_args(argv)
    folders: list[Path] = args.folders
    out: Path = args.out

    labels: list[Label] = []
    runs: list[str] = []
    # A folder given twice would count its reviews twice and narrow the
    # bound, the unsafe side: each counts once.
    for folder in dict.fromkeys(folder.resolve() for folder in folders):
        try:
            labels += read_reviewed_run(folder, RECEIPT)
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
        problem = _breaks_the_sequence(load_policy(out), target=args.target, runs=runs)
        if problem:
            print(f"{out}: {problem}", file=sys.stderr)
            return 1
    policy = calibrate(labels, RECEIPT, target=args.target, audit_rate=args.audit_rate, runs=runs)
    # Through a temporary file: a scheduled run may load the policy meanwhile.
    temporary = out.with_name(f".{out.name}.tmp")
    temporary.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(out)  # atomic on one filesystem (os.replace)
    print(render(policy))
    return 0


def _breaks_the_sequence(previous: AcceptancePolicy, *, target: float, runs: list[str]) -> str:
    """Why a new policy cannot replace ``previous``, or "" when it can.

    The bound holds however often it is looked at only along one growing
    sequence of labels, checked against one target fixed in advance
    (docs/ARCHITECTURE.md D22). Leaving out a run with an error, or moving the
    target, would pick the result.
    """
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


def render(policy: AcceptancePolicy) -> str:
    """The policy as a table: names left-aligned, numbers right-aligned."""
    bounds = upper_bounds(policy, RECEIPT)
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
    fields = len(RECEIPT.schema.model_fields)
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
