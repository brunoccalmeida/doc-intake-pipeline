"""The golden sets the eval scores, each with its pack, baseline and recordings (#69).

- ``sroie``: 20 public scanned receipts; the set and its recordings stay out of
  this repository (no licence, ``docs/DATA.md``). The default, so every
  documented ``uv run poe eval`` command keeps its meaning.
- ``fatura``: 20 template-generated invoices (CC BY 4.0) on layouts the prompt
  was not tuned on; the set and its recordings are committed.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from doc_intake.core.config import Settings
from doc_intake.core.extract import Pack
from doc_intake.core.llm import LLMProvider
from doc_intake.core.runlog import new_run_id
from doc_intake.packs.invoice import INVOICE, Invoice
from doc_intake.packs.receipt import RECEIPT, Receipt
from evals.baseline import BASELINE_PATH
from evals.cross_fit import CrossFit, cross_fit
from evals.fatura import GOLDEN_DIR as FATURA_DIR
from evals.run import EvalRun, run_eval
from evals.scoring import DocumentScore
from evals.sroie import MANIFEST_PATH, load_manifest

_EVALS = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class Suite[S: BaseModel]:
    """One golden set: what it scores and where its evidence lives.

    ``title`` heads the report; ``described`` and ``noun`` word the README
    summary ("Measured on 20 {described}", "per {noun}").
    """

    name: str
    pack: Pack[S]
    ids: Callable[[], list[str]]
    golden_dir: Callable[[Settings], Path]
    recordings_dir: Callable[[Settings], Path]
    baseline: Path
    report: Path
    title: str
    described: str
    noun: str

    def evaluate(
        self, ids: Sequence[str], provider: LLMProvider, settings: Settings
    ) -> tuple[EvalRun, CrossFit, list[DocumentScore]]:
        """Score ``ids``, then each again under the policy of the others where it accepts (D22)."""
        golden_dir = self.golden_dir(settings)

        def score(
            document_ids: Sequence[str], accept: Mapping[str, frozenset[str]] | None
        ) -> EvalRun:
            return run_eval(
                document_ids,
                self.pack,
                provider,
                golden_dir=golden_dir,
                tessdata_dir=settings.tessdata_dir,
                run_id=new_run_id(),
                provider_name=settings.provider,
                max_retries=settings.max_retries,
                accept=accept,
            )

        run = score(ids, None)
        fit = cross_fit(run.scores, run.from_image, self.pack)
        rescored = score(list(fit.accepts), fit.accepts).scores if fit.accepts else []
        return run, fit, rescored


def _sroie_ids() -> list[str]:
    return [entry.id for entry in load_manifest(MANIFEST_PATH).receipts]


def _fatura_ids() -> list[str]:
    return sorted(path.stem for path in FATURA_DIR.glob("*.json"))


SUITES: dict[str, Suite[Receipt] | Suite[Invoice]] = {
    "sroie": Suite(
        name="sroie",
        pack=RECEIPT,
        ids=_sroie_ids,
        golden_dir=lambda settings: settings.sroie_dir,
        recordings_dir=lambda settings: settings.recordings_dir,
        baseline=BASELINE_PATH,
        report=Path(".cache/eval/report.md"),
        title="SROIE receipts",
        described="public scanned receipts",
        noun="receipt",
    ),
    "fatura": Suite(
        name="fatura",
        pack=INVOICE,
        ids=_fatura_ids,
        golden_dir=lambda _: FATURA_DIR,
        recordings_dir=lambda _: _EVALS / "recordings" / "fatura",
        baseline=_EVALS / "baseline-fatura.json",
        report=Path(".cache/eval/report-fatura.md"),
        title="FATURA invoices (template-generated, so scores overstate real invoices)",
        described="public template-generated invoices",
        noun="invoice",
    ),
}
DEFAULT = "sroie"
