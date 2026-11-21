"""The README's eval summary, written from an eval run between two markers (#40).

The README quotes the eval to clients, so its numbers come from the run, not
from a hand-typed copy: ``uv run poe eval --update-readme`` rewrites the block,
and a full eval fails when the committed block differs from the run (a
re-recording or a price change would otherwise leave it stale in silence).
Like the report, it holds counts and cost only, never document content.
"""

from decimal import Decimal

from evals.run import EvalRun
from evals.scoring import ReviewLoad, field_accuracy, review_load

START = "<!-- eval-summary:start (written by `uv run poe eval --update-readme`) -->"
END = "<!-- eval-summary:end -->"

_CENT = Decimal("0.01")


class ReadmeMarkerError(ValueError):
    """The README does not hold the summary markers exactly once, in order."""


def render_summary(run: EvalRun) -> str:
    accuracy = field_accuracy(run.scores)
    load = ReviewLoad.total(review_load(run.scores).values())
    values = sum(total for _, total in accuracy.values())
    correct = sum(right for right, _ in accuracy.values())
    usage = run.usage
    average = usage.average_cost_usd
    if average is None:
        raise ValueError("an eval run without documents has no summary")
    return "\n".join(
        [
            f"Measured on {usage.documents} public scanned receipts, {values} values in all "
            f"({', '.join(accuracy)}):",
            "",
            f"- **{correct} of {values} correct.**",
            f"- **{load.accepted} accepted automatically**, {_wrong(load.wrong_accepted)}.",
            f"- **{load.review} sent to a person to check**, {_wrong(load.wrong_review)}.",
            f"- **{load.empty} left empty**, with the reason.",
            f"- **{_dollars(usage.cost_usd)} for the whole set**, "
            f"{_dollars(average, rounded='about ')} per receipt.",
        ]
    )


def _dollars(amount: Decimal, *, rounded: str = "") -> str:
    """To the cent; a cost that rounds to zero is not free, so it reads "under $0.01"."""
    cents = amount.quantize(_CENT)
    if cents == 0 and amount > 0:
        return "under $0.01"
    return f"{rounded}${cents}"


def replace_summary(readme: str, summary: str) -> str:
    """``readme`` with the text between the markers replaced by ``summary``."""
    start, end = readme.find(START), readme.find(END)
    if readme.count(START) != 1 or readme.count(END) != 1 or end < start:
        raise ReadmeMarkerError(f"the README must hold {START} and then {END}, once each")
    return f"{readme[: start + len(START)]}\n{summary}\n{readme[end:]}"


def _wrong(count: int) -> str:
    return "none of them wrong" if count == 0 else f"{count} of them wrong"
