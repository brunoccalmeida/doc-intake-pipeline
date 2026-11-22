"""Run the eval on the SROIE golden set and gate on the committed baseline.

    uv run poe eval                    # replay the recordings: no key, no cost (what CI runs)
    uv run poe eval --record           # call the provider for unrecorded requests: COSTS MONEY
    uv run poe eval --update-baseline  # make the current scores the new baseline (commit it)
    uv run poe eval --update-readme    # rewrite the README's eval summary (commit it)

A full run (no ``--ids``) also fails when the README's eval summary differs
from the run, so the numbers shown to clients never go stale (#40).

The recordings directory (``DOC_INTAKE_RECORDINGS_DIR``) is a clone of the
private recordings repository (``docs/DATA.md``). Writes the Markdown report
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
from doc_intake.core.runlog import new_run_id
from doc_intake.packs.receipt import RECEIPT
from doc_intake.providers import make_provider
from evals.baseline import BASELINE_PATH, load_baseline, regressions, save_baseline
from evals.readme import render_summary, replace_summary
from evals.recording import MissingRecordingError, RecordingProvider, RecordingStore, ReplayProvider
from evals.report import render_report
from evals.run import run_eval
from evals.scoring import field_accuracy, review_load
from evals.sroie import MANIFEST_PATH, load_manifest
from scripts.logs import configure_run_log

REPORT_PATH = Path(".cache/eval/report.md")
README_PATH = Path("README.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="call the real provider (paid)")
    mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline")
    parser.add_argument("--ids", nargs="+", help="score only these receipts (the gate then fails)")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--update-readme", action="store_true", help="rewrite the README's eval summary"
    )
    parser.add_argument("--readme", type=Path, default=README_PATH)
    args = parser.parse_args(argv)
    if args.update_readme and args.ids:
        parser.error("--update-readme needs the whole set: the README quotes it, not a subset")
    baseline_path: Path = args.baseline
    report_path: Path = args.report
    readme_path: Path = args.readme

    settings = Settings()
    configure_run_log(settings.log_level)
    # Before anything is read or recorded: an unpriced model would be paid for
    # and then fail when its cost is computed.
    price_of(settings.model)
    store = RecordingStore(settings.recordings_dir)
    provider: LLMProvider
    if args.record:
        # Built first: a missing key fails here, before any document is read.
        provider = RecordingProvider(
            make_provider(settings), store, provider=settings.provider, model=settings.model
        )
    else:
        provider = ReplayProvider(store, provider=settings.provider, model=settings.model)
    ids: list[str] = args.ids or [entry.id for entry in load_manifest(MANIFEST_PATH).receipts]

    try:
        run = run_eval(
            ids,
            RECEIPT,
            provider,
            golden_dir=settings.sroie_dir,
            tessdata_dir=settings.tessdata_dir,
            run_id=new_run_id(),
            provider_name=settings.provider,
            max_retries=settings.max_retries,
        )
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
    # A subset cannot match the README's whole-set numbers, so only a full run checks
    # them; and only a passing one: the fix for a worse score is the code, and
    # writing the README then would publish the worse numbers.
    if not args.ids and not found:
        readme = readme_path.read_text(encoding="utf-8")
        current = replace_summary(readme, render_summary(run))
        if args.update_readme:
            readme_path.write_text(current, encoding="utf-8", newline="\n")
        elif current != readme:
            found.append(
                f"{readme_path}: the eval summary is out of date; "
                "run `uv run poe eval --update-readme` and commit it"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(run, baseline, regressions=found), encoding="utf-8")
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


if __name__ == "__main__":
    sys.exit(main())
