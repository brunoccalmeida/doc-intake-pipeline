"""Render an eval run as Markdown: the gate verdict first, then the evidence.

The report is public (the CI job summary and artifact), so it holds ids, field
names, outcomes and usage only; ``DocumentScore`` carries no document content
by construction (AGENTS.md invariant 6, ``docs/DATA.md``).
"""

from core.pricing import PRICE_SOURCES
from evals.baseline import Baseline
from evals.run import EvalRun
from evals.scoring import ReviewLoad, field_accuracy, review_load, status_counts


def render_report(run: EvalRun, baseline: Baseline | None, *, regressions: list[str]) -> str:
    lines = ["# Eval report: SROIE receipts", ""]
    if regressions:
        lines += ["**Gate: failed.**", "", *(f"- {problem}" for problem in regressions)]
    else:
        lines.append(
            "**Gate: passed.** No field scored below the baseline "
            "or accepted more wrong values than it."
        )

    lines += ["", "## Accuracy per field", "", "| Field | Correct | Accuracy | Baseline |"]
    lines.append("| --- | --- | --- | --- |")
    for name, (correct, total) in field_accuracy(run.scores).items():
        expected = (
            f"{baseline.fields[name]}/{baseline.documents}"
            if baseline is not None and name in baseline.fields
            else "none"
        )
        lines.append(f"| {name} | {correct}/{total} | {correct / total:.1%} | {expected} |")

    lines += ["", "## Review load per field", ""]
    lines += [
        "Accepted values reach the client unchecked; values sent to review wait for a "
        "person, and so does every field of a failed document. Wrong means a value that "
        "differs from the golden record or should be empty. The gate holds wrong accepted "
        "values at or below the baseline.",
        "",
        "| Field | Accepted | Wrong accepted | Baseline | Sent to review "
        "| Wrong in review | Empty |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    loads = review_load(run.scores)
    for name, load in loads.items():
        limit = (
            str(baseline.wrong_accepted[name])
            if baseline is not None and name in baseline.wrong_accepted
            else "none"
        )
        lines.append(_load_row(name, load, limit))
    limit = (
        str(sum(baseline.wrong_accepted.values()))
        if baseline is not None and set(loads) <= set(baseline.wrong_accepted)
        else "none"
    )
    lines.append(_load_row("**All fields**", ReviewLoad.total(loads.values()), limit))

    counts = status_counts(run.scores)
    lines += ["", "## Documents by status", ""]
    lines += [f"| {' | '.join(counts)} |", f"|{' --- |' * len(counts)}"]
    lines.append(f"| {' | '.join(str(count) for count in counts.values())} |")

    lines += ["", "## Failures", ""]
    failures: list[str] = []
    for score in run.scores:
        if score.status == "failed" and set(score.fields.values()) <= {"document_failed"}:
            cause = f" ({score.error})" if score.error else ""
            failures.append(f"| {score.id} | all | document failed{cause} |")
            continue
        failures += [
            f"| {score.id} | {name} | {outcome} |"
            for name, outcome in score.fields.items()
            if outcome != "correct"
        ]
    if failures:
        lines += ["| Document | Field | Outcome |", "| --- | --- | --- |", *failures]
    else:
        lines.append("None.")

    usage = run.usage
    lines += ["", "## Usage", ""]
    lines += [
        "| Documents | Calls | Input tokens | Output tokens | Cost (USD) "
        "| Average per document (USD) | Models |"
    ]
    lines += ["| --- | --- | --- | --- | --- | --- | --- |"]
    average = "none" if usage.average_cost_usd is None else f"${usage.average_cost_usd}"
    lines.append(
        f"| {usage.documents} | {usage.calls} | {usage.input_tokens} | {usage.output_tokens} "
        f"| ${usage.cost_usd} | {average} | {', '.join(usage.models) or 'none'} |"
    )
    lines += [
        "",
        "Tokens are those of the recorded calls; prices from "
        + "; ".join(f"{url} (checked on {date})" for url, date in PRICE_SOURCES.items())
        + ".",
        "",
    ]
    return "\n".join(lines)


def _load_row(name: str, load: ReviewLoad, limit: str) -> str:
    return (
        f"| {name} | {load.accepted} | {load.wrong_accepted} | {limit} | {load.review} "
        f"| {load.wrong_review} | {load.empty} |"
    )
