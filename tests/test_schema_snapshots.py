"""The JSON Schema a provider receives is committed, so any change shows up in review.

The schema is the contract with the LLM: changing it changes what the model is
asked to return and can move eval scores. An accidental change (a renamed field,
a dropped constraint) must fail here instead of reaching the prompt unnoticed.
"""

import pytest

from packs.json_schema import PACKS_DIR, SCHEMAS, render, snapshot_path

FIX = "run `uv run poe export-schemas` and commit the diff"


@pytest.mark.parametrize("pack", sorted(SCHEMAS))
def test_json_schema_matches_committed_snapshot(pack: str) -> None:
    path = snapshot_path(pack)
    assert path.is_file(), f"missing {path}; {FIX}"
    assert render(SCHEMAS[pack]) == path.read_text(encoding="utf-8"), (
        f"the {pack} JSON Schema changed. If intended, {FIX}; otherwise undo the change."
    )


def test_every_snapshot_belongs_to_a_registered_pack() -> None:
    # A snapshot whose pack was renamed or removed would go stale unnoticed.
    committed = {path.parent.name for path in PACKS_DIR.glob("*/*.schema.json")}
    assert committed == set(SCHEMAS)
