"""Render an eval run as Markdown: the gate verdict first, then the evidence.

The report is public (the CI job summary and artifact), so it holds ids, field
names, outcomes and usage only; ``DocumentScore`` carries no document content
by construction (AGENTS.md invariant 6, ``docs/DATA.md``).
"""

from core.pricing import PRICES_CHECKED_ON, PRICES_SOURCE
from evals.baseline import Baseline
from evals.run import EvalRun
from evals.scoring import field_accuracy, status_counts


def render_report(run: EvalRun, baseline: Baseline | None, *, regressions: list[str]) -> str:
    lines = ["# Eval report: SROIE receipts", ""]
    if regressions:
        lines += ["**Gate: failed.**", "", *(f"- {problem}" for problem in regressions)]
    else:
        lines.append("**Gate: passed.** No field scored below the baseline.")

    lines += ["", "## Accuracy per field", "", "| Field | Correct | Accuracy | Baseline |"]
    lines.append("| --- | --- | --- | --- |")
    for name, (correct, total) in field_accuracy(run.scores).items():
        expected = (
            f"{baseline.fields[name]}/{baseline.documents}"
            if baseline is not None and name in baseline.fields
            else "none"
        )
        lines.append(f"| {name} | {correct}/{total} | {correct / total:.1%} | {expected} |")

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
    lines += ["| Calls | Input tokens | Output tokens | Cost (USD) | Models |"]
    lines += ["| --- | --- | --- | --- | --- |"]
    lines.append(
        f"| {usage.calls} | {usage.input_tokens} | {usage.output_tokens} "
        f"| ${usage.cost_usd} | {', '.join(usage.models) or 'none'} |"
    )
    lines += [
        "",
        f"Tokens are those of the recorded calls; prices checked on {PRICES_CHECKED_ON} "
        f"at {PRICES_SOURCE}.",
        "",
    ]
    return "\n".join(lines)
