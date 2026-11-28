"""Export each pack's JSON Schema, the contract a provider is asked to fill.

The rendered schemas are committed next to their packs and a snapshot test
compares them with the models, so a schema change is always a visible diff.
Regenerate with ``uv run poe export-schemas``.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from doc_intake.packs.invoice import Invoice
from doc_intake.packs.receipt import Receipt

PACKS_DIR = Path(__file__).parent
SCHEMAS: dict[str, type[BaseModel]] = {"invoice": Invoice, "receipt": Receipt}


def snapshot_path(pack: str) -> Path:
    return PACKS_DIR / pack / f"{pack}.schema.json"


def render(model: type[BaseModel]) -> str:
    """Stable text: fixed indentation, UTF-8 kept readable, final newline."""
    return json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


def export() -> list[Path]:
    written: list[Path] = []
    for pack, model in SCHEMAS.items():
        path = snapshot_path(pack)
        path.write_text(render(model), encoding="utf-8", newline="\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in export():
        print(path.relative_to(PACKS_DIR.parent))
