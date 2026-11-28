"""Run the eval on a golden set and gate on its committed baseline.

    uv run poe eval                    # replay the recordings: no key, no cost (what CI runs)
    uv run poe eval --suite fatura     # the same on the FATURA invoices (default: sroie)
    uv run poe eval --record           # call the provider for unrecorded requests: COSTS MONEY
    uv run poe eval --update-baseline  # make the current scores the new baseline (commit it)
    uv run poe eval --update-readme    # rewrite the README's eval summary (commit it)

A full run (no ``--ids``) also fails when the README's eval summary differs
from the run, so the numbers shown to clients never go stale (#40).

The SROIE recordings directory (``DOC_INTAKE_RECORDINGS_DIR``) is a clone of the
private recordings repository; the FATURA ones are committed (``docs/DATA.md``,
``evals.suites``). Writes the Markdown report
and exits 1 when the gate fails or a recording is missing; the report holds
ids, field names and outcomes only, so CI can publish it. Each document is
also logged on stderr as a JSON line (``doc_intake.core.runlog``), with no content either.
"""

import argparse
import sys
from pathlib import Path

from doc_intake.core.config import Settings
from doc_intake.core.llm import LLMProvider
from doc_intake.core.pricing import price_of
from doc_intake.providers import make_provider
from evals.baseline import load_baseline, regressions, save_baseline
from evals.cross_fit import render_cross_fit
from evals.readme import markers, render_summary, replace_summary
from evals.recording import MissingRecordingError, RecordingProvider, RecordingStore, ReplayProvider
from evals.report import render_report
from evals.scoring import field_accuracy, review_load
from evals.suites import DEFAULT, SUITES
from scripts.logs import configure_run_log

README_PATH = Path("README.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="call the real provider (paid)")
    mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline")
    parser.add_argument("--suite", choices=sorted(SUITES), default=DEFAULT)
    parser.add_argument("--ids", nargs="+", help="score only these documents (the gate then fails)")
    parser.add_argument("--baseline", type=Path, help="default: the suite's")
    parser.add_argument("--report", type=Path, help="default: the suite's")
    parser.add_argument(
        "--update-readme", action="store_true", help="rewrite the README's eval summary"
    )
    parser.add_argument("--readme", type=Path, default=README_PATH)
    args = parser.parse_args(argv)
    if args.update_readme and args.ids:
        parser.error("--update-readme needs the whole set: the README quotes it, not a subset")
    suite = SUITES[args.suite]
    baseline_path: Path = args.baseline or suite.baseline
    report_path: Path = args.report or suite.report
    readme_path: Path = args.readme

    settings = Settings()
    configure_run_log(settings.log_level)
    # Before anything is read or recorded: an unpriced model would be paid for
    # and then fail when its cost is computed.
    price_of(settings.model)
    store = RecordingStore(suite.recordings_dir(settings))
    provider: LLMProvider
    if args.record:
        # Built first: a missing key fails here, before any document is read.
        provider = RecordingProvider(
            make_provider(settings), store, provider=settings.provider, model=settings.model
        )
    else:
        provider = ReplayProvider(store, provider=settings.provider, model=settings.model)
    ids: list[str] = args.ids or suite.ids()

    try:
        run, fit, rescored = suite.evaluate(ids, provider, settings)
    except MissingRecordingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    accuracy = field_accuracy(run.scores)
    load = review_load(run.scores)
    if args.update_baseline:
        save_baseline(baseline_path, accuracy, load)
    baseline = load_baseline(baseline_path) if baseline_path.is_file() else None
    found = (
        regressions(accuracy, load, baseline)
        if baseline is not None
        else [f"no baseline at {baseline_path}"]
    )
    # Zero, not a baseline: a wrong value no person checks is invented data
    # reaching the client (AGENTS.md invariant 1).
    wrong_auto = fit.wrong_accepted(rescored)
    found += [
        f"{name}: {count} wrong values accepted from the image by a cross-fitted policy, above 0"
        for name, count in wrong_auto.items()
        if count
    ]
    # A subset cannot match the README's whole-set numbers, so only a full run checks
    # them; and only a passing one: the fix for a worse score is the code, and
    # writing the README then would publish the worse numbers.
    if not args.ids and not found:
        readme = readme_path.read_text(encoding="utf-8")
        start, end = markers(suite.name)
        summary = render_summary(run, described=suite.described, noun=suite.noun)
        current = replace_summary(readme, summary, start_marker=start, end_marker=end)
        if args.update_readme:
            readme_path.write_text(current, encoding="utf-8", newline="\n")
        elif current != readme:
            found.append(
                f"{readme_path}: the eval summary is out of date; "
                f"run `{_command(suite.name)} --update-readme` and commit it"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(
        run,
        baseline,
        regressions=found,
        auto_acceptance=render_cross_fit(fit, wrong=wrong_auto),
        title=suite.title,
    )
    report_path.write_text(report, encoding="utf-8")
    usage = run.usage
    print(
        f"documents={usage.documents} calls={usage.calls} input_tokens={usage.input_tokens} "
        f"output_tokens={usage.output_tokens} cost_usd={usage.cost_usd} "
        f"average_cost_usd={usage.average_cost_usd} report={report_path}",
        file=sys.stderr,
    )
    if found:
        print(
            "ERROR: eval gate failed:", *(f"  {line}" for line in found), sep="\n", file=sys.stderr
        )
        return 1
    return 0


def _command(suite: str) -> str:
    return "uv run poe eval" if suite == DEFAULT else f"uv run poe eval --suite {suite}"


if __name__ == "__main__":
    sys.exit(main())
