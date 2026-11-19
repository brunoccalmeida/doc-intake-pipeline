"""Extract one receipt with the configured real provider. Costs money: run on purpose.

    uv run poe extract path/to/receipt.pdf

Prints the validated result as JSON on stdout (it holds document content, so
it is never logged) and, on stderr, the calls made, the tokens used and the
model that answered, from which the run's cost is computed. Per-document cost
in the run log is #7.
"""

import argparse
import sys
from pathlib import Path

from core.config import Settings
from core.extract import extract
from core.ingest import ingest
from core.llm import Metered
from packs.receipt import RECEIPT
from providers import make_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("path", type=Path, help="PDF, PNG or JPEG of one receipt")
    args = parser.parse_args(argv)
    path: Path = args.path

    settings = Settings()
    document = ingest(path, tessdata_dir=settings.tessdata_dir)
    provider = Metered(make_provider(settings))
    result = extract(document, RECEIPT, provider, max_retries=settings.max_retries)

    print(result.model_dump_json(indent=2))
    models = sorted({response.model for response in provider.responses})
    print(
        f"provider={settings.provider} models={','.join(models)} calls={len(provider.responses)} "
        f"input_tokens={sum(r.input_tokens for r in provider.responses)} "
        f"output_tokens={sum(r.output_tokens for r in provider.responses)} "
        f"status={result.status}",
        file=sys.stderr,
    )
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
