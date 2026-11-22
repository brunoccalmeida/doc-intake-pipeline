"""The release cooldown binds every lock, not only Dependabot (#55, D7).

Dependabot waits 7 days before proposing a release, but a manual ``uv lock``
or ``uv add`` used to take whatever was newest: in #14 and #11 releases one to
three days old entered by hand. ``exclude-newer`` in uv's configuration closes
that path, and uv records the relative span in each lock (``[options]``), so
the lock is what proves the cooldown applied to its resolution. These tests
read the committed locks and fail when one was resolved without the cooldown
or with a different length than Dependabot's.
"""

import re
import tomllib
from pathlib import Path
from typing import cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCKS = [ROOT / "uv.lock", ROOT / "demo" / "voice.py.lock"]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


def _mapping(value: object, what: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{what} is not a mapping"
    # cast after the runtime check: isinstance proved dict, cast names its items
    return {str(k): v for k, v in cast("dict[object, object]", value).items()}


def _lock_span_days(lock: Path) -> int:
    options = _mapping(
        tomllib.loads(lock.read_text(encoding="utf-8")).get("options", {}), f"{lock.name} [options]"
    )
    span = options.get("exclude-newer-span")
    assert isinstance(span, str), (
        f"{lock.relative_to(ROOT)} was resolved without a relative exclude-newer: set "
        '`exclude-newer = "7 days"` in its [tool.uv] and lock again'
    )
    # uv writes the span as an ISO 8601 duration; whole days is what Dependabot counts
    match = re.fullmatch(r"P(\d+)D", span)
    assert match, f"{lock.relative_to(ROOT)}: span {span!r} is not a whole number of days"
    return int(match.group(1))


def _dependabot_uv_cooldown_days() -> int:
    updates = _mapping(yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8")), DEPENDABOT.name)[
        "updates"
    ]
    assert isinstance(updates, list)
    for entry in cast("list[object]", updates):
        update = _mapping(entry, "update")
        if update.get("package-ecosystem") == "uv":
            days = _mapping(update.get("cooldown"), "uv cooldown").get("default-days")
            assert isinstance(days, int), "the uv ecosystem has no cooldown default-days"
            return days
    pytest.fail("dependabot.yml has no uv ecosystem")


@pytest.mark.parametrize("lock", LOCKS, ids=lambda path: path.name)
def test_lock_was_resolved_with_dependabots_cooldown(lock: Path) -> None:
    assert _lock_span_days(lock) == _dependabot_uv_cooldown_days()
